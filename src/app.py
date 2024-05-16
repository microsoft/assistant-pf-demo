import json
import os
import chainlit as cl
import base64

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from assistant_flow.chat import chat_completion

from promptflow.tracing import start_trace
from dotenv import load_dotenv
import logging
load_dotenv()

def setup_app_insights():
    from promptflow.tracing._integrations._openai_injector import inject_openai_api
    inject_openai_api()

    # dial down the logs for azure monitor -- it is so chatty
    azmon_logger = logging.getLogger('azure')
    azmon_logger.setLevel(logging.WARNING)

    # Set the Tracer Provider
    trace.set_tracer_provider(TracerProvider())

    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    # Configure Azure Monitor as the Exporter
    print("using the follwoing connection string", os.getenv('APPINSIGHTS_CONNECTION_STRING'))
    trace_exporter = AzureMonitorTraceExporter(
        connection_string=os.getenv('APPINSIGHTS_CONNECTION_STRING')
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

def show_images(image):
    elements = [
        cl.Image(
            content=image,
            name="generated image",
            display="inline",
        )
    ]
    return elements


async def call_promptflow(chat_history, message):

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("call_promptflow") as span:
        carrier = {}
        # Write the current context into the carrier.
        TraceContextTextMapPropagator().inject(carrier)
        cl.user_session.set("last_message_context", carrier)

        span.set_attribute("inputs", json.dumps({"question": message.content}))
        span.set_attribute("span_type", "function")
        span.set_attribute("framework", "promptflow")
        span.set_attribute("function", "call_promptflow")

        session_state = cl.user_session.get("session_state")

        response = await cl.make_async(chat_completion)(question=message.content,
                                                        session_state=session_state)
        
        try:            
            span.set_attribute("output", json.dumps(response))
        except Exception as e:
            span.set_attribute("output", str(e))

    return response

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
 
    if question.startswith("/upvote"):
        await feedback("upvote")
    elif question.startswith("/downvote"):
        await feedback("downvote")
    else:

        from chainlit import make_async, run_sync

        msg = cl.Message(content="")
        await msg.send()

        reply = await call_promptflow(chat_history, message)
        if "session_state" in reply:
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
    return cl.Image(content=data, name="generated image", display="inline", size="large")

if __name__ == "__main__":
    start_trace()
    setup_app_insights()

    print("using the follwoing chat_model", os.getenv("OPENAI_CHAT_MODEL"))

    from chainlit.cli import run_chainlit
    run_chainlit(__file__)
