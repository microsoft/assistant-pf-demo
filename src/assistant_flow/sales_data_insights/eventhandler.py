
from openai import AssistantEventHandler
from typing_extensions import override
from openai.types.beta import AssistantStreamEvent
from openai.types.beta.threads import (
    Run,
    Text,
    Message,
    ImageFile,
    TextDelta,
    MessageDelta,
    MessageContent,
    MessageContentDelta,
)
from openai.types.beta.threads.runs import RunStep, ToolCall, RunStepDelta, ToolCallDelta


class EventHandler(AssistantEventHandler):
    def __init__(self, thread_id, assistant_id):
        super().__init__()
        self.output = None
        self.tool_id = None
        self.thread_id = thread_id
        self.assistant_id = assistant_id
        self.run_id = None
        self.run_step = None
        self.function_name = ""
        self.arguments = ""
      
    @override
    def on_text_created(self, text) -> None:
        print(f"\nassistant on_text_created > ", end="", flush=True)

    @override
    def on_text_delta(self, delta, snapshot):
        # print(f"\nassistant on_text_delta > {delta.value}", end="", flush=True)
        print(f"{delta.value}")

    @override
    def on_end(self, ):
        print(f"\n end assistant > ",self.current_run_step_snapshot, end="", flush=True)

    @override
    def on_exception(self, exception: Exception) -> None:
        """Fired whenever an exception happens during streaming"""
        print(f"\nassistant > {exception}\n", end="", flush=True)

    @override
    def on_message_created(self, message: Message) -> None:
        print(f"\nassistant on_message_created > {message}\n", end="", flush=True)

    @override
    def on_message_done(self, message: Message) -> None:
        print(f"\nassistant on_message_done > {message}\n", end="", flush=True)

    @override
    def on_message_delta(self, delta: MessageDelta, snapshot: Message) -> None:
        # print(f"\nassistant on_message_delta > {delta}\n", end="", flush=True)
        pass

    @override
    def on_tool_call_created(self, tool_call: ToolCall):
        print(f"\nassistant on_tool_call_created > {tool_call}")
        
    @override
    def on_tool_call_done(self, tool_call: ToolCall) -> None:       
        print(f"\nassistant on_tool_call_done > {tool_call}")
        
        
    @override
    def on_run_step_created(self, run_step: RunStep) -> None:
        # 2       
        print(f"on_run_step_created")
        self.run_id = run_step.run_id
        self.run_step = run_step
        print("The type of run_step run step is ", type(run_step), flush=True)
        print(f"\n run step created assistant > {run_step}\n", flush=True)

    @override
    def on_run_step_done(self, run_step: RunStep) -> None:
        print(f"\n run step done assistant > {run_step}\n", flush=True)

    @override
    def on_tool_call_delta(self, delta, snapshot): 
        if delta.type == 'function':
            # the arguments stream thorugh here and then you get the requires action event
            print(delta.function.arguments, end="", flush=True)
            self.arguments += delta.function.arguments
        elif delta.type == 'code_interpreter':
            print(f"on_tool_call_delta > code_interpreter")
            if delta.code_interpreter.input:
                print(delta.code_interpreter.input, end="", flush=True)
            if delta.code_interpreter.outputs:
                print(f"\n\noutput >", flush=True)
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        print(f"\n{output.logs}", flush=True)
        else:
            print("ELSE")
            print(delta, end="", flush=True)

    @override
    def on_event(self, event: AssistantStreamEvent) -> None:
        # print("In on_event of event is ", event.event, flush=True)

        if event.event == "thread.run.requires_action":
            print("\nthread.run.requires_action > submit tool call")
            print(f"ARGS: {self.arguments}")
