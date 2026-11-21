# OpenAI meeting agent

Send an interactive meeting agent to Google Meet, Zoom, Microsoft Teams, or Webex. It answers questions aloud and takes spoken requests to share a webpage, post in meeting chat where available, or leave the call.

Recall streams meeting audio directly to OpenAI Realtime. The app uses a server-side connection to handle meeting tools, mute, and listening controls. See [Recall's OpenAI integration](https://docs.recall.ai/docs/meeting-agents-openai).

## Behavior

Start each request with **“Assistant”** or **“openai demo”**, followed by a question or command. The agent joins silently. Where chat is available, it posts an introduction and tool feedback there. Requested messages and links are their own confirmation.

| Action | Tool |
| --- | --- |
| Start or replace a screen share with a public webpage | `start_screenshare(url)` |
| Post requested text in meeting chat | `send_chat_message(message)` |
| Post the exact last accepted page URL | `send_current_page_link()` |
| Stop the screen share while keeping conversation available | `stop_screenshare()` |
| Post a departure message and leave the meeting | `leave_call()` |
| Silence speech; keep tools available | `mute_agent()` |
| Enable new speech | `unmute_agent()` |
| Pause answers and actions | `stop_listening()` |
| Resume requests; preserve the mute setting | `start_listening()` |

Mute controls speech only; tools remain available. Stop listening pauses requests until a standalone **“Assistant, start listening”** command, preserving mute. Audio still reaches OpenAI so the restart command can be recognized. Skipped requests and unheard answers are never replayed.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- A Recall workspace and its regional REST API key.
- An OpenAI project key with access to the selected Realtime model and `gpt-4o-mini-transcribe`, configured in both Recall's dashboard and the local environment.
- A meeting link and permission to admit the bot if prompted.
- A network that permits outbound HTTPS and secure WebSocket connections.

## Quickstart

Set up and run the sample locally.

### 1. Clone the repository and install dependencies

```sh
git clone https://github.com/recallai/agent-demo-openai.git
cd agent-demo-openai
uv sync --locked
```

### 2. Configure the environment

Create the local configuration file:

```sh
cp .env.example .env
```

Fill in the ignored root `.env`. Credentials stay on the server; process environment variables take precedence.

| Variable | Value |
| --- | --- |
| `RECALL_API_KEY` | REST API key for the Recall workspace. |
| `RECALL_API_BASE_URL` | Matching regional API URL, such as `https://us-east-1.recall.ai/api/v1`. |
| `OPENAI_API_KEY` | OpenAI project key matching the integration configured in Recall. |
| `REALTIME_MODEL` | Realtime model; the example uses `gpt-realtime-2.1`. |
| `REALTIME_VOICE` | Realtime voice; the example uses `marin`. |
| `REALTIME_REASONING_EFFORT` | `low` in the example, or `default` to use the model default. |
| `CONNECT_TIMEOUT_SECONDS` | Time allowed for admission and provider startup; defaults to `300`. |
| `SESSION_TIMEOUT_SECONDS` | Maximum connected session duration; defaults to `600`. |
| `LAUNCHER_PORT` | Local launcher port; defaults to `8003`. |

Restart the app and launch a new bot after changing `.env`. Model and reasoning settings must be supported by your OpenAI project.

### 3. Connect Recall to OpenAI

Open **Agents → OpenAI** in the Recall region and workspace matching `RECALL_API_KEY`. Save the same OpenAI project key you set in `.env`. Find the dashboard link for your region in the [Recall OpenAI setup guide](https://docs.recall.ai/docs/meeting-agents-openai#setup).

### 4. Start the app

From the repository root:

```sh
uv run --locked python -m app.web
```

Keep this process running, then open [the launcher](http://127.0.0.1:8003). Keep the launcher bound to localhost.

### 5. Send the agent to a meeting

For your first test, start a Google Meet call at [meet.new](https://meet.new/). You can also use a link from any supported platform. Paste the direct meeting link into the launcher, select **Send agent**, and admit **openai demo** if prompted. Wait for the launcher to report **Ready**.

### 6. Try the agent

Use a public HTTPS URL that loads without signing in, and verify the page appears in the meeting. Use Zoom, Google Meet, or Microsoft Teams for the chat commands and loading notices. [Recall chat support](https://docs.recall.ai/docs/sending-chat-messages)

| Try saying |
| --- |
| “Assistant, what is two plus two?” |
| “Assistant, show https://example.com.” |
| “Assistant, send the shared webpage link in chat.” |
| “Assistant, mute.” |
| “Assistant, post Hello from the demo in chat.” |
| “Assistant, stop sharing.” |
| “Assistant, unmute.” |
| “Assistant, stop listening.” |
| “Assistant, start listening.” |
| “Assistant, leave the meeting.” |

After the bot leaves, stop the process with Ctrl+C. The session defaults to 10 minutes; launch a new bot to repeat the demo. Leaving removes only the bot.

## Code map

| File | Responsibility |
| --- | --- |
| `app/web.py` | Local launcher, session status, deadlines, and bot cleanup. |
| `app/templates/index.html` | Meeting-URL form and request status. |
| [`app/agent.py`](app/agent.py) | Configure Realtime, discover the call, and compose the session. |
| `app/meeting_agent.py` | Admit addressed requests and coordinate Realtime responses. |
| `app/meeting_tools.py` | Nine actions, listening/mute state, and the last page URL. |
| `app/tool_execution.py` | Validate arguments and prevent duplicate action attempts. |
| `app/realtime.py` | OpenAI control connection, events, cancellation, and audio clearing. |
| `app/instructions.py` | Conversation guidance and the introductory chat message. |
| [`app/recall_client.py`](app/recall_client.py) | Build the Create Bot request, look up the call ID, and make Recall tool requests. |
| `app/tool_schema.py` | OpenAI function definitions for the nine tools. |
| `app/request_filter.py` | Recognize agent addresses and the standalone restart command. |
| `app/config.py` | Load and validate environment settings. |

Recall creates a four-core bot on each supported platform with `output_media.audio.kind = "openai"`. Recall sends audio directly to OpenAI and plays the response into the meeting. The app retains the bot ID returned by Create Bot.

The launcher finds the call ID by querying the bot's `openai_session_created` log through Recall's undocumented `POST /api/v1/logs` endpoint. It uses that ID to attach a server-side connection for tools and response control. Recall carries the meeting audio directly to and from OpenAI. [OpenAI server controls](https://developers.openai.com/api/docs/guides/voice-server-controls#with-webrtc)

Input transcription gates addressed requests before responses or interruptions. Five tools call Recall; four control speech and listening. Webpage sharing is separate from voice, so stopping it preserves conversation.

## Boundaries and troubleshooting

- If Create Bot returns HTTP 400, check that the OpenAI key is saved under **Agents → OpenAI** in the same Recall region and workspace as `RECALL_API_KEY`.
- If the agent never becomes ready, check meeting admission and whether the workspace's REST API key can read customer-visible logs.
- If the voice connection fails, check that the local OpenAI key belongs to the same project as the dashboard key and has access to the configured models.
- If the agent is silent, start with “Assistant” and check meeting chat for mute/listening state. Unmute restores speech; start listening restores request handling.
- Chat messages are limited to 500 characters. Tool-feedback failures do not repeat or undo the original action.
- The agent can display public pages but cannot read, summarize, click, scroll, or sign in to them. Some websites may not load. A successful API request does not verify rendering.
- The last accepted URL remains available after sharing stops or a later request fails. Sharing does not automatically post the URL.
- The app does not save meeting content. Recall recordings follow your workspace's retention settings; the app does not delete them.
