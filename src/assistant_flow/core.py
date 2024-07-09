# enable type annotation syntax on Python versions earlier than 3.9
from __future__ import annotations

import time
import os
import logging
import json

from openai import AzureOpenAI

from promptflow.tracing import trace
from opentelemetry import trace as otel_trace
from opentelemetry import context as otel_context
from promptflow.contracts.multimedia import Image
from threading import Thread

tracer = otel_trace.get_tracer(__name__)

class AssistantAPI:
    @trace
    def __init__(
        self,
        client: AzureOpenAI,
        session_state: dict[str, any] = None,
        tools: dict[str, callable] = None,
    ):
        # Provision an AzureOpenAI client for the assistants
        logging.info("Creating AzureOpenaI client")
        self.client = client
        self.tools = tools or {}

        self.max_waiting_time = 120

        session_state = session_state or {}
        if "thread_id" in session_state:
            logging.info(f"Using thread_id from session_stat: {session_state['thread_id']}")
            self.thread_id = self.client.beta.threads.retrieve(session_state['thread_id']).id
        else:
            logging.info(f"Creating a new thread")
            self.thread_id = self.client.beta.threads.create().id


        if "OPENAI_ASSISTANT_ID" in os.environ:
            logging.info(
                f"Using assistant_id from environment variables: {os.getenv('OPENAI_ASSISTANT_ID')}"
            )
            self.assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
        else:
            raise Exception(
                "You need to provide OPENAI_ASSISTANT_ID in the environment variables"
            )



    def start(self, question):
        # run handler in a separate thread
        # Capture the current context
        current_context = otel_context.get_current()
        self.queue = QueuedIteratorStream()
        # print(f"current_context {current_context}")
        def run_with_context():
            # Reactivate the captured context in the new thread
            logging.info("Thread started")
            token = otel_context.attach(current_context)
            try:
                self.run(question)
            finally:
                otel_context.detach(token)
            logging.info("Thread ended")

        # run handler in a separate thread with context
        thread = Thread(target=run_with_context)
        thread.start()
        
        return dict(
            chat_output=self.queue.iter(),
            session_state={ "thread_id": self.thread_id },
            planner_raw_output=None
        )


    @trace    
    def run(self, question):
        self.question = question

        run = None
        start_time = time.time()

        # get current span
        span = otel_trace.get_current_span()
        span.set_attribute("promptflow.assistant.message", self.question)
        span.set_attribute("promptflow.assistant.thread_id", self.thread_id)
        span.set_attribute("promptflow.assistant.assistant_id", self.assistant_id)
        
        logging.info("Submitting the message")
        _ = self.client.beta.threads.messages.create(
            thread_id=self.thread_id,
            role="user",
            content=question,
        )

        logging.info("Streaming the run")
        with self.client.beta.threads.runs.stream(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id,
            event_handler=EventHandler(self.client, self.queue),
        ) as stream:

            for event in stream:
                if ((time.time() - start_time) > self.max_waiting_time):
                    # todo: in case of timeout, the current_run might not be populated yet
                    run = stream.current_run
                    logging.info(f"streaming timed out")
                    logging.info(f"Run status: {stream.current_run.status}")
                    break
            logging.info(f"done streaming")
            logging.info(f"Run status: {stream.current_run.status}")
            run = stream.current_run
    
        span.set_attribute("promptflow.assistant.run_id", run.id)
        logging.info(f"thread.run.created: run.id {run.id}")


        # loop while action is required or until max_waiting_time is reached
        while ((time.time() - start_time) < self.max_waiting_time) and run.status == "requires_action":
            logging.info(
                f"Run status: {run.status} (time={int(time.time() - start_time)}s, max_waiting_time={self.max_waiting_time})"
            )

            tool_call_outputs = []

            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                # trace_tool(tool_call.model_dump())
                # self.queue.send(f"\nTool call: {tool_call.function.name} with arguments: {tool_call.function.arguments}\n")

                if tool_call.type == "function":
                    tool_func = self.tools[tool_call.function.name]
                    tool_call_output = tool_func(
                        **json.loads(tool_call.function.arguments)
                    )

                    tool_call_outputs.append(
                        {
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(tool_call_output),
                        }
                    )
                else:
                    raise ValueError(f"Unsupported tool call type: {tool_call.type}")
               
            logging.info("Resuming streaming the run")
            with self.client.beta.threads.runs.submit_tool_outputs_stream(
                thread_id=self.thread_id,
                run_id=run.id,
                tool_outputs=tool_call_outputs,
                event_handler=EventHandler(self.client, self.queue),
            ) as stream:
                logging.info(f"Stream status: {stream}")
                for event in stream:
                    if ((time.time() - start_time) > self.max_waiting_time):
                        # todo: in case of timeout, the current_run might not be populated yet
                        run = stream.current_run
                        logging.info(f"streaming timed out")
                        logging.info(f"Run status: {stream.current_run.status}")
                        break
                run = stream.current_run
                logging.info(f"done streaming")
                logging.info(f"Run status: {stream.current_run.status}")

        if run.status == "completed":
            span.set_attribute("llm.response.model", run.model)
            span.set_attribute("llm.usage.completion_tokens", run.usage.completion_tokens)
            span.set_attribute("llm.usage.prompt_tokens", run.usage.prompt_tokens)
            span.set_attribute("llm.usage.total_tokens", run.usage.total_tokens)

            
        elif run.status in ["cancelled", "expired", "failed"]:
            self.queue.send(f"Run failed with status: {run.last_error}")
            logging.info(f"Run status: {run.last_error}")

        elif run.status in ["in_progress", "queued"]:
            logging.info(f"Run status: {run.status}. The run has timed out.")
            try: 
                # the run could have complete by now, so do this in a try/except block
                run = self.client.beta.threads.runs.cancel(
                    thread_id=self.thread_id, run_id=run.id
                )
            except Exception as e:
                logging.error(f"Failed to cancel the run: {e}")
            self.queue.send(f"The run has timed out after {self.max_waiting_time} seconds.")

        else:
            raise ValueError(f"Unknown run status: {run.status}")

        self.queue.end()
        return
    

from openai import AssistantEventHandler
from typing_extensions import override
from openai.types.beta.threads import ImageFile, Message

class EventHandler(AssistantEventHandler): 
    def __init__(self, client, queue):
        self.client = client
        self.queue = queue
        self.tool_calls_done = []
        super().__init__()

    @override
    def on_text_created(self, text) -> None:
        self.queue.send(f"\n")
        
    @override
    def on_text_delta(self, delta, snapshot):
        self.queue.send(delta.value)
        
    def text_message(self, content):
        with tracer.start_as_current_span("assistant.text_message") as span:
            span.set_attribute("framework", "promptflow")
            span.set_attribute("span_type", "Function")
            span.set_attribute("function", "assistant.text_message")
            span.set_attribute("inputs", json.dumps(content.text.value.split("\n")))

    def image_message(self, content):
        image = Image(self.client.files.content(content.image_file.file_id).read())
        with tracer.start_as_current_span("assistant.image_message") as span:
            span.set_attribute("framework", "promptflow")
            span.set_attribute("span_type", "Function")
            span.set_attribute("function", "assistant.image_message")
            span.set_attribute("inputs", image.to_base64(with_type=True))

    @override
    def on_tool_call_created(self, tool_call):
        self.queue.send(f"\n> tool_call: {tool_call.type}\n")
        if tool_call.type == "function":
            self.queue.send(f"> id  : {tool_call.id}\n")
            self.queue.send(f"> name: {tool_call.function.name}\n> arguments: ")
        elif tool_call.type == "code_interpreter":
            self.queue.send(f"> id  : {tool_call.id}\n\n")
        
    @override
    def on_message_done(self, message: Message) -> None:
        for content in message.content:
            if content.type == "text":
                self.text_message(content)
            elif content.type == "image_file":
                self.image_message(content)

    @override
    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            pass
            # if delta.code_interpreter.input:
            #     self.queue.send(delta.code_interpreter.input)
            # if delta.code_interpreter.outputs:
            #     self.queue.send(f"\n\noutput >\n")
            #     for output in delta.code_interpreter.outputs:
            #         if output.type == "logs":
            #             self.queue.send(f"\n{output.logs}\n")
        elif delta.type == "function":
            self.queue.send(delta.function.arguments)
        else:
            self.queue.send(delta)

    @override
    def on_image_file_done(self, image_file: ImageFile):
        file_id = image_file.file_id
        image = Image(self.client.files.content(file_id).read())
        self.queue.send(image)


    @override
    def on_tool_call_done(self, tool_call):
        # events seem to be duplicated, so we need to keep track of the tool calls that have been processed
        if tool_call.id in self.tool_calls_done:
            return
        self.tool_calls_done.append(tool_call.id)

        self.queue.send("\n")

        # submit tool call to telemetry
        print(f"\ntool_call: {tool_call.type}", flush=True)
        if tool_call.type == "function":
            with tracer.start_as_current_span("assistant.function_call") as span:
                span.set_attribute("frmaework", "promptflow")
                span.set_attribute("span_type", "Function")
                span.set_attribute("function", "function_call")
                span.set_attribute("inputs", tool_call.function.arguments)
                span.set_attribute("inputs", json.dumps(dict(name=tool_call.function.name,
                                                             arguments=json.loads(tool_call.function.arguments),
                                                             tool_call_id=tool_call.id)))

        elif tool_call.type == "code_interpreter":
            with tracer.start_as_current_span("code_interpreter_call") as span:
                span.set_attribute("framework", "promptflow")
                span.set_attribute("span_type", "Function")
                span.set_attribute("function", "code_interpreter_call")

                if tool_call.code_interpreter.input:
                    span.set_attribute("inputs", json.dumps(dict(code=tool_call.code_interpreter.input.split("\n"),
                                                                 tool_call_id=tool_call.id)))
                
                if tool_call.code_interpreter.outputs:
                    output_dict = {}
                    for output in tool_call.code_interpreter.outputs:
                        if output.type == "logs":
                            output_dict["logs"] = output.logs.split("\n")
                        elif output.type == "image":
                            output_dict["image_file_id"] =  output.image.file_id
                            file_id = output.image.file_id
                            image_base64 = Image(self.client.files.content(file_id).read()).to_base64(with_type=True)
                            output_dict["image_base64"] = image_base64
                
                    span.set_attribute("output", json.dumps(output_dict))
        else:
            with tracer.start_as_current_span("tool_call") as span:
                span.set_attribute("promptflow.assistant.tool_call", str(tool_call))


import queue
import json
from typing import Any, Dict, List
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry import trace

class QueuedIteratorStream:
    terminate: str = "<--terminate-->"
    queue: queue.Queue[str]
    output: List[str]
    context_carrier: Dict[str, Any]

    def __init__(self) -> None:
        self.queue = queue.Queue()
        self.output = []
        self.context_carrier = {}
        # Write the current context into the carrier.
        TraceContextTextMapPropagator().inject(self.context_carrier)

    def send(self, event: str) -> None:
        if event is not None and event != "":
            if isinstance(event, Image):
                self.output.append(f"\n{event.to_base64(with_type=True)}\n")
                self.queue.put_nowait(f"\n\n![]({event.to_base64(with_type=True)})\n\n")
            else:
                self.output.append(event)
                self.queue.put_nowait(event)

    def end(self) -> None:
        tracer = trace.get_tracer(__name__)
        ctx = TraceContextTextMapPropagator().extract(carrier=self.context_carrier)

        with tracer.start_as_current_span("stream", context=ctx) as span:
            span.set_attribute("framework", "promptflow")
            span.set_attribute("span_type", "Function")
            span.set_attribute("function", "stream")
            reformatted_output :str = "".join(self.output)
            span.set_attribute("output", json.dumps(reformatted_output.split("\n")))

        self.queue.put_nowait(self.terminate)

    def iter(self) -> Any:
        while True:
            token = self.queue.get()

            if token == self.terminate:
                break

            yield token

