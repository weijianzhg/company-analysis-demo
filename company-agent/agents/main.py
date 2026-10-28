"""Company analyst on the blueprint's AgentCore HTTP runtime (port 8080)."""

from contextvars import copy_context
import os
from queue import Empty, Queue
from threading import Lock, Thread

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from analyst import analyze

app = BedrockAgentCoreApp()
invocation_lock = Lock()
HEARTBEAT_SECONDS = 10


def prompt_events(prompt: str):
    if not invocation_lock.acquire(blocking=False):
        yield {"error": "Agent is busy; retry after the current request finishes"}
        return
    completed = Queue(maxsize=1)

    def run():
        try:
            response = analyze(prompt)
        except Exception as exc:
            # Avoid printing provider exception bodies or credential-bearing URLs.
            app.logger.error("Analysis failed (%s)", type(exc).__name__)
            response = {"error": f"Analysis failed ({type(exc).__name__}); check MCP_URL, model settings and credentials"}
        finally:
            invocation_lock.release()
        completed.put(response)

    worker = Thread(target=copy_context().run, args=(run,), daemon=True)
    try:
        worker.start()
    except Exception:
        invocation_lock.release()
        raise
    yield {"type": "heartbeat"}
    while True:
        try:
            yield completed.get(timeout=HEARTBEAT_SECONDS)
            return
        except Empty:
            yield {"type": "heartbeat"}


@app.entrypoint
def invoke(payload: dict):
    if not isinstance(payload, dict):
        return {"error": "payload must be an object"}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10000:
        return {"error": "prompt must be a non-empty string of at most 10000 characters"}
    return prompt_events(prompt)


if __name__ == "__main__":
    app.run(host=os.environ.get("AGENT_HOST", "127.0.0.1"),
            port=int(os.environ.get("AGENT_PORT", "8080")))
