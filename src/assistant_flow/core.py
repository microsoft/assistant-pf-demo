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
fun_emojis = ["🏃‍♂️", "🏃‍♀️", "🚶‍♂️", "🚶‍♀️", "🚶", "🏃", "🚶‍♂️", "🚶‍♀️", "🏃‍♂️", "🏃‍♀️"]

class AssistantsAPIGlue:
    def __init__(
        self,
        client: AzureOpenAI,
        question: str,
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
            otel_trace.get_current_span().set_attribute("AssistantsAPIGlue_thread_id",  session_state['thread_id'])
            self.thread_id = self.client.beta.threads.retrieve(session_state['thread_id']).id
        else:
            logging.info(f"Creating a new thread")
            self.thread_id = self.client.beta.threads.create().id
            otel_trace.get_current_span().set_attribute("AssistantsAPIGlue_thread_id", self.thread_id)

        # Add last message in the thread
        logging.info("Adding message in the thread")
        self.add_message(dict(role="user", content=question))

        if "OPENAI_ASSISTANT_ID" in os.environ:
            logging.info(
                f"Using assistant_id from environment variables: {os.getenv('OPENAI_ASSISTANT_ID')}"
            )
            self.assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
        else:
            raise Exception(
                "You need to provide OPENAI_ASSISTANT_ID in the environment variables"
            )
        # get current span
        otel_trace.get_current_span().set_attribute("AssistantsAPIGlue_assistant_id", self.assistant_id)

    def add_message(self, message):
        _ = self.client.beta.threads.messages.create(
            thread_id=self.thread_id,
            role=message["role"],
            content=message["content"],
        )

    @trace
    def run(self, messages=None):
        # run handler in a separate thread
        # Capture the current context
        current_context = otel_context.get_current()
        self.queue = QueuedIteratorStream()

        def run_with_context():
            # Reactivate the captured context in the new thread
            token = otel_context.attach(current_context)
            try:
                self.run_inner(messages)
            finally:
                otel_context.detach(token)

        # run handler in a separate thread with context
        thread = Thread(target=run_with_context)
        thread.start()
        
        return dict(
            chat_output=self.queue.iter(),
            session_state={ "thread_id": self.thread_id },
            planner_raw_output=None
        )
        


    def run_inner(self, messages=None):
        if messages:
            logging.info("Adding last message in the thread")
            _ = self.client.beta.threads.messages.create(
                thread_id=self.thread_id,
                role=messages[-1]["role"],
                content=messages[-1]["content"],
            )

        # Run the thread
        logging.info("Running the thread")
        run = self.client.beta.threads.runs.create(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id,
        )
        logging.info(f"Run status: {run.status}")
        self.queue.send(f"\nRunning message on Thread: {self.thread_id}\n")

        start_time = time.time()

        # loop until max_waiting_time is reached
        while (time.time() - start_time) < self.max_waiting_time:
            # checks the run regularly
            run = self.client.beta.threads.runs.retrieve(
                thread_id=self.thread_id, run_id=run.id
            )
            logging.info(
                f"Run status: {run.status} (time={int(time.time() - start_time)}s, max_waiting_time={self.max_waiting_time})"
            )

            if run.status == "completed":
                # check run steps
                run_steps = self.client.beta.threads.runs.steps.list(
                    thread_id=self.thread_id, run_id=run.id #, after=step_logging_cursor
                )

                for step in reversed(list(run_steps)):
                    log_step(step.model_dump())

                messages = []
                for message in self.client.beta.threads.messages.list(
                    thread_id=self.thread_id
                ):
                    message = self.client.beta.threads.messages.retrieve(
                        thread_id=self.thread_id, message_id=message.id
                    )
                    messages.append(message)
                logging.info(f"Run completed with {len(messages)} messages.")

                final_message = messages[0]

                mixed_response = []

                for message in final_message.content:
                    if message.type == "text":
                        mixed_response.append(message.text.value)
                    elif message.type == "image_file":
                        file_id = message.image_file.file_id
                        mixed_response.append(
                            Image(self.client.files.content(file_id).read())
                        )
                    else:
                        logging.critical("Unknown content type: {}".format(message.type))

                for response in mixed_response:
                    self.queue.send(response)
                
                self.queue.end()

                return
            
            elif run.status == "requires_action":
                # if the run requires us to run a tool
                tool_call_outputs = []

                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    trace_tool(tool_call.model_dump())
                    self.queue.send(f"\nTool call: {tool_call.function.name} with arguments: {tool_call.function.arguments}\n")

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

                if tool_call_outputs:
                    _ = self.client.beta.threads.runs.submit_tool_outputs(
                        thread_id=self.thread_id,
                        run_id=run.id,
                        tool_outputs=tool_call_outputs,
                    )
            elif run.status in ["cancelled", "expired", "failed"]:
                raise ValueError(f"Run failed with status: {run.status}")

            elif run.status in ["in_progress", "queued"]:
                # fun running emoji                
                # self.queue.send(f"{fun_emojis[int(time.time()) % len(fun_emojis)]}")
                self.queue.send(".")
                time.sleep(2)

            else:
                raise ValueError(f"Unknown run status: {run.status}")

def log_step(step):
    logging.info(
            "The assistant has moved forward to step {}".format(step["id"])
    )
    step_details = step["step_details"]
    if step_details["type"] == "tool_calls":
        for tool_call in step_details["tool_calls"]:
            if tool_call["type"] == "code_interpreter":
                python_code = tool_call["code_interpreter"]["input"].split("\n")
                output = tool_call["code_interpreter"]["outputs"]
                trace_code_interpreter(python_code, output)

@trace
def trace_code_interpreter(python_code, output):
    logging.info(
            "The assistant executed code interpretation of {}".format(python_code)
    )

@trace
def trace_tool(tool_call):
    logging.info(
            "The assistant has asks for tool execution of {}".format(tool_call["function"]["name"])
    )



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
                self.output.append(event.to_base64(with_type=True))
                self.queue.put_nowait(f"\n\n![]({event.to_base64(with_type=True)})\n\n")
            else:
                self.output.append(event)
                self.queue.put_nowait(f"{event}")

    def end(self) -> None:
        tracer = trace.get_tracer(__name__)
        ctx = TraceContextTextMapPropagator().extract(carrier=self.context_carrier)

        with tracer.start_as_current_span("stream", context=ctx) as span:
            span.set_attribute("framework", "promptflow")
            span.set_attribute("span_type", "Function")
            span.set_attribute("function", "stream")
            span.set_attribute("output", json.dumps(self.output))

        self.queue.put_nowait(self.terminate)

    def iter(self) -> Any:
        while True:
            token = self.queue.get()

            if token == self.terminate:
                break

            yield token

