import json
import ast
import os
import inspect
import requests
from openai import AsyncAzureOpenAI
from urllib.parse import quote
from chainlit.playground.providers.openai import stringify_function_call
import chainlit as cl
import base64
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from promptflow.client import PFClient
from promptflow.tracing import start_trace
from dotenv import load_dotenv
load_dotenv()

def setup_app_insights():
    from promptflow.tracing._integrations._openai_injector import inject_openai_api
    inject_openai_api()

    # Set the Tracer Provider
    trace.set_tracer_provider(TracerProvider())

    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    # Configure Azure Monitor as the Exporter
    print("using the follwoing connection string", os.getenv('APPINSIGHTS_INSTRUMENTATIONKEY'))
    trace_exporter = AzureMonitorTraceExporter(
        connection_string=os.getenv('APPINSIGHTS_INSTRUMENTATIONKEY')
    )

    # Add the Azure exporter to the tracer provider
    trace.get_tracer_provider().add_span_processor(
        SimpleSpanProcessor(trace_exporter)
    )

    # Configure Console as the Exporter
    file = open('spans.json', 'w')

    # Configure Console as the Exporter and pass the file object
    console_exporter = ConsoleSpanExporter(out=file)

    # Add the console exporter to the tracer provider
    trace.get_tracer_provider().add_span_processor(
        SimpleSpanProcessor(console_exporter)
    )
    # Get a tracer
    return trace.get_tracer(__name__) 

@cl.on_chat_start
def start_chat():
    print("starting chat")

    cl.user_session.set(
        "chat_history",
        [],
    )
    cl.user_session.set("last_message_context", None)
    cl.user_session.set("session_state", {})

    promptflows = [
        os.path.join(os.path.dirname(__file__), 'assistant_flow'),
        os.path.join(os.path.dirname(__file__), 'data_analyst'),
    ]

    config = dict(
        active_promptflow = promptflows[0],
        promptflows = promptflows,
    )
    cl.user_session.set("config", config)
    

def show_images(image):
    elements = [
        cl.Image(
            content=image,
            name="generated image",
            display="inline",
        )
    ]
    return elements


def call_promptflow(chat_history, message):

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("call_promptflow") as span:
        carrier = {}
        # Write the current context into the carrier.
        TraceContextTextMapPropagator().inject(carrier)
        cl.user_session.set("last_message_context", carrier)

        # from functions_flow.functions_flow import run_conversation
        # response = await run_conversation(chat_history=chat_history, 
        #                                 question=message.content)

        span.set_attribute("inputs", json.dumps({"question": message.content}))
        span.set_attribute("span_type", "function")
        span.set_attribute("framework", "promptflow")
        span.set_attribute("function", "call_promptflow")

        # prompt_flow = cl.user_session.get("config")["active_promptflow"]
        # client = PFClient()
        # response = await cl.make_async(client.test)(prompt_flow, 
        #                                               inputs={"chat_history": chat_history,
        #                                                       "question": message.content})
        # from data_analyst.functions_flow import run_conversation
        # response = await run_conversation(chat_history=chat_history, 
        #                                    question=message.content)
        session_state = cl.user_session.get("session_state")

        from assistant_flow.pf_planner import chat_completion
        response = chat_completion(question=message.content,
                                    session_state=session_state)

        try:            
            span.set_attribute("output", json.dumps(response))
        except Exception as e:
            span.set_attribute("output", str(e))

    return response

async def activate_promptflow(command: str, command_id: str):
    config = cl.user_session.get("config")
    if len(command.split(" ")) < 2:
        await cl.Message(content=f"#### Promptflow is currently set to `{config['active_promptflow']}`").send()
        return
    
    promptflow_number = int(command.split(" ")[1])
    if promptflow_number < 0 or promptflow_number >= len(config["promptflows"]):
        await cl.Message(content=f"#### Invalid promptflow number `{promptflow_number}` -- needs to be between 0 and {len(config['promptflows'])}").send()
        return

    config["active_promptflow"] = config["promptflows"][promptflow_number]
    await cl.Message(content=f"#### Set promptflow to `{config['active_promptflow']}`").send()

    cl.user_session.set(
        "chat_history",
        [],
    )

async def feedback(feedback_type):
    tracer = trace.get_tracer(__name__)
    last_message_context = cl.user_session.get("last_message_context")
    if last_message_context is None:
        await cl.Message(content=f"#### no last message set").send()
        return

    ctx = TraceContextTextMapPropagator().extract(carrier=last_message_context)

    with tracer.start_as_current_span("user_feedback", context=ctx) as span:
        span.set_attribute("evaluation", "user_feedback")
        span.set_attribute("output", json.dumps({"feedback": feedback_type}))


    await cl.Message(content=f"#### Feedback recorded: {feedback_type} for {last_message_context}").send()
    return

@cl.on_message
async def run_conversation(message: cl.Message):
    question = message.content 
    chat_history = cl.user_session.get("chat_history")
 
    if question.startswith("/activate"):
        await activate_promptflow(message.content, message.id)
    elif question.startswith("/upvote"):
        await feedback("upvote")
    elif question.startswith("/downvote"):
        await feedback("downvote")
    else:

        from chainlit import make_async, run_sync

        msg = cl.Message(content="")
        await msg.send()

        reply = await make_async(call_promptflow)(chat_history, message)
        cl.user_session.set("session_state", reply["session_state"])
        stream = reply["chat_output"]
        response = ""
        images = []
        for thing in stream:

            if thing.strip().startswith("!["):
                image = parse_image(thing.strip())
                images.append(image)
                msg.elements = images
            else:
                response += thing
                msg.content = response
            
            await msg.update()
        await msg.stream_token("🏁")
        
        chat_history.append({"inputs": {"question": message.content}, 
                            "outputs": {"answer": response}})
        
def parse_image(thing):
    # parse the image data from this inline markdown image
    # ![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAABjElEQVRIS+2VvUoDQRSGv)
    image = thing.split("(data:image/png;base64,")[1].split(")")[0]
    data = base64.b64decode(image)
    return cl.Image(content=data, name="generated image", display="inline")

if __name__ == "__main__":
    start_trace()
    setup_app_insights()

    print("using the follwoing chat_model", os.getenv("OPENAI_CHAT_MODEL"))

    from chainlit.cli import run_chainlit
    run_chainlit(__file__)
