import json
import os
import chainlit as cl
import base64
from time import time_ns

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
import opentelemetry
from opentelemetry import _logs # _log is an unfortunate hack that will eventually be resolved on the OTel side with a new Event API
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor,  ConsoleSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.span import TraceFlags
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, ConsoleLogExporter
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter, AzureMonitorTraceExporter

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
    print("using the following connection string", os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING'))
    trace_exporter = AzureMonitorTraceExporter(
        connection_string=os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING')
    )

    # Add the Azure exporter to the tracer provider
    trace.get_tracer_provider().add_span_processor(
        SimpleSpanProcessor(trace_exporter)
    )

    # Configure Console as the Exporter
    file = open('spans.json', 'w')

    console_exporter = ConsoleSpanExporter(out=file)
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(console_exporter))

    provider = LoggerProvider()
    _logs.set_logger_provider(provider)
    console_exporter = ConsoleLogExporter(out=file)
    provider.add_log_record_processor(SimpleLogRecordProcessor(console_exporter))
    provider.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING'))))

    # Get a tracer
    return trace.get_tracer(__name__) 

@cl.on_chat_start
def start_chat():
    print("starting chat")

    cl.user_session.set("last_message_context", None)
    cl.user_session.set("session_state", {})    


@cl.action_callback("upvote")
async def on_action(action):
    span_context = json.loads(action.value)
    log_evaluation_event(name="user_vote", scores={"vote": 1}, span_context=span_context, message="User upvoted the answer")

@cl.action_callback("downvote")
async def on_action(action):
    span_context = json.loads(action.value)
    log_evaluation_event(name="user_vote", scores={"vote": 0}, span_context=span_context, message="User downvoted the answer")


def show_images(image):
    elements = [
        cl.Image(
            content=image,
            name="generated image",
            display="inline",
        )
    ]
    return elements


async def call_promptflow(message):

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


def log_evaluation_event(name: str, scores: dict, span_context: dict, message: str) -> None:
    trace_id = int(span_context["traceparent"].split("-")[1], 16)
    span_id = int(span_context["traceparent"].split("-")[2], 16)
    trace_flags = TraceFlags(int(span_context["traceparent"].split("-")[3], 16))
    # print(trace_id, span_id, trace_flags)
    
    attributes = {"event.name": f"gen_ai.evaluation.{name}"}
    for key, value in scores.items():
        attributes[f"gen_ai.evaluation.{key}"] = value

    event = opentelemetry.sdk._logs.LogRecord(
        timestamp=time_ns(),
        observed_timestamp=time_ns(),
        trace_id=trace_id,
        span_id=span_id,
        trace_flags=trace_flags,
        severity_text=None,
        severity_number=_logs.SeverityNumber.UNSPECIFIED,
        body=message,
        attributes=attributes
    )

    _logs.get_logger(__name__).emit(event)

async def feedback(feedback_type, trace_context):
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

    from chainlit import make_async, run_sync

    msg = cl.Message(content="")
    await msg.send()

    reply = await call_promptflow(message)
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
    await msg.update()

    last_message_context = cl.user_session.get("last_message_context")
    last_message_context_json = json.dumps(last_message_context)
    # Sending an action button within a chatbot message
    actions = [
        cl.Action(name="upvote", value=last_message_context_json, description="Click me if you like the answer!"),
        cl.Action(name="downvote", value=last_message_context_json, description="Click me if you don't like the answer!")
    ]

    await cl.Message(content="Rate the Chatbot's answer:", actions=actions).send()

        
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
