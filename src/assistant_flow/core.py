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
            token = otel_context.attach(current_context)
            try:
                self.run(question)
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

    def process_event(self, event):
        if event.event == "thread.run.created":
            span = otel_trace.get_current_span()
            span.set_attribute("promptflow.assistant.run_id", event.data.id)
            logging.info(f"thread.run.created: run.id {event.data.id}")
        elif event.event == "thread.message.in_progress":
            print("\n**** message in progress ****\n")
        elif event.event == "thread.message.delta":
            delta = event.data.delta.content[0]
            if delta.type == "text":
                print(delta.text.value, end="", flush=True)
            elif delta.type == "image_file":
                file_id = delta.image_file.file_id
                image_base64 = Image(self.client.files.content(file_id).read()).to_base64(with_type=True)
                print(f"![]({image_base64[:40]})", end="", flush=True)
            else:
                print(delta)
        elif event.event == "thread.run.step.in_progress":
            print("\n**** step in progress ****\n")
        elif event.event == "thread.run.step.delta":
            step_details = event.data.delta.step_details
            if step_details.type == "tool_calls":
                for tool_call in step_details.tool_calls:
                    if not tool_call.id is None:
                        # this is the header
                        print(f"  tool_call:")
                        if tool_call.type == "function":
                            print(f"    type: {tool_call.type}")
                            print(f"    id  : {tool_call.id}")
                            print(f"    name: {tool_call.function.name}")
                        elif tool_call.type == "code_interpreter":
                            print(f"    type: {tool_call.type}")
                        else:
                            print(f"    type: {tool_call.type}")
                    else:
                        # this is the body
                        if tool_call.type == "function":
                            print(tool_call.function.arguments, end="", flush=True)
                        elif tool_call.type == "code_interpreter":
                            if tool_call.code_interpreter.input:
                                print(tool_call.code_interpreter.input, end="", flush=True)
                            elif tool_call.code_interpreter.outputs:
                                for output in tool_call.code_interpreter.outputs:
                                    if output.type == "logs":
                                        print(f"\n{output.logs}", flush=True)
                            else:
                                print(tool_call)
                        else:
                            print(tool_call)
            
        else:
            logging.info(f"Streaming event: {event.event}")        

    @trace    
    def run(self, question):
        self.question = question

        # Run the thread
        # logging.info("Running the thread")
        # run = self.client.beta.threads.runs.create(
        #     thread_id=self.thread_id,
        #     assistant_id=self.assistant_id,
        # )
        # logging.info(f"Run status: {run.status}")
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
            timeout=self.max_waiting_time,
        ) as stream:
            logging.info(f"Stream status: {stream}")
            for event in stream:
                self.process_event(event)
            logging.info(f"done streaming")
            logging.info(f"Run status: {stream.current_run.status}")
            run = stream.current_run

        # self.queue.send(f"\nRunning message on Thread: {self.thread_id}\n")


        # loop until max_waiting_time is reached
        while (time.time() - start_time) < self.max_waiting_time:
            # checks the run regularly
            # run = self.client.beta.threads.runs.retrieve(
            #     thread_id=self.thread_id, run_id=run.id
            # )
            logging.info(
                f"Run status: {run.status} (time={int(time.time() - start_time)}s, max_waiting_time={self.max_waiting_time})"
            )

            if run.status == "completed":
                span.set_attribute("llm.response.model", run.model)
                span.set_attribute("llm.usage.completion_tokens", run.usage.completion_tokens)
                span.set_attribute("llm.usage.prompt_tokens", run.usage.prompt_tokens)
                span.set_attribute("llm.usage.total_tokens", run.usage.total_tokens)

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
                span.set_attribute("llm.generated_message", final_message.model_dump())

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
                    # _ = self.client.beta.threads.runs.submit_tool_outputs(
                    #     thread_id=self.thread_id,
                    #     run_id=run.id,
                    #     tool_outputs=tool_call_outputs,
                    # )
                    logging.info("Resuming streaming the run")
                    with self.client.beta.threads.runs.submit_tool_outputs_stream(
                        thread_id=self.thread_id,
                        run_id=run.id,
                        tool_outputs=tool_call_outputs,
                        timeout=self.max_waiting_time - (time.time() - start_time),
                    ) as stream:
                        logging.info(f"Stream status: {stream}")
                        for event in stream:
                            self.process_event(event)
                        run = stream.current_run
                        logging.info(f"done streaming")
                        logging.info(f"Run status: {stream.current_run.status}")

            elif run.status in ["cancelled", "expired", "failed"]:
                raise ValueError(f"Run failed with status: {run.status}")

            elif run.status in ["in_progress", "queued"]:
                raise ValueError(f"Status should not occur when streaming: {run.status}")
                # fun running emoji                
                # self.queue.send(f"{fun_emojis[int(time.time()) % len(fun_emojis)]}")
                # self.queue.send(".")
                # time.sleep(2)

            else:
                raise ValueError(f"Unknown run status: {run.status}")

        run = self.client.beta.threads.runs.cancel(
            thread_id=self.thread_id, run_id=run.id
        )
        self.queue.send("The run has timed out.")
        self.queue.end()
        return
    
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
                trace_code_interpreter(python_code, step["usage"], output)
            else:
                trace_usage(step["usage"])
    else: 
        trace_usage(step["usage"])
@trace
def trace_usage(usage):
    logging.info(
            "The assistant has used the following tokens: {}".format(usage)
    )

@trace
def trace_code_interpreter(python_code, usage, output):
    logging.info(
            "The assistant executed code interpretation of {}".format(python_code)
    )

@trace
def trace_tool(tool_call):
    logging.info(
            "The assistant has asks for tool execution of {}".format(tool_call["function"]["name"])
    )

from openai import AssistantEventHandler
from typing_extensions import override

class EventHandler(AssistantEventHandler):    
  @override
  def on_text_created(self, text) -> None:
    print(f"\nassistant > ", end="", flush=True)
      
  @override
  def on_text_delta(self, delta, snapshot):
    print(delta.value, end="", flush=True)
      
  def on_tool_call_created(self, tool_call):
    print(f"\nassistant > {tool_call.type}\n", flush=True)
  
  def on_tool_call_delta(self, delta, snapshot):
    if delta.type == 'code_interpreter':
      if delta.code_interpreter.input:
        print(delta.code_interpreter.input, end="", flush=True)
      if delta.code_interpreter.outputs:
        print(f"\n\noutput >", flush=True)
        for output in delta.code_interpreter.outputs:
          if output.type == "logs":
            print(f"\n{output.logs}", flush=True)

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

