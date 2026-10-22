import os
import uuid
import json
import tempfile
import streamlit as st

from typing import List
from semente import Image, Audio, File

from semente.configs.config import config
from semente.interfaces.streamlit.debug_helpers import extract_workflow_debug_data, extract_session_state
from semente.interfaces.streamlit.debug_panel import render_debug_panel
from semente.core.harness import get_harness

st.set_page_config(page_title="Semente", page_icon="🌱")

DB_FILE = "users_db.json"

# ==================== DATABASE ====================

def get_users():
    if not os.path.exists(DB_FILE):
        return []
    
    try:
        with open(DB_FILE, "r") as file:
            return json.load(file)
    except:
        return []

def new_user(user_id, user_name):
    users = get_users()

    if not any(user['id'] == user_id for user in users):
        users.append({"id": user_id, "nickname": user_name})
        with open(DB_FILE, "w") as f:
            json.dump(users, f, indent=4)

def login_user(user_id, user_name="Anonymous"):
    st.session_state["session_id"] = user_id
    st.session_state["user_name"] = user_name
    st.session_state["logged_in"] = True
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    st.rerun()

def logout():
    st.session_state["logged_in"] = False
    st.session_state["session_id"] = None
    st.session_state["user_name"] = None
    st.session_state["messages"] = []

    # Clear debug state
    st.session_state.debug_log = []
    st.session_state.debug_session_state = {}
    st.session_state.debug_agent_routing = []
    st.session_state.debug_tool_calls = []
    st.session_state.debug_metrics = []
    st.session_state.debug_messages = []

    st.rerun()

# ==================== LOGIN SCREEN ====================

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("Login")

    col1, col2, col3 = st.columns(3)

    # 1. Stored user list
    with col1:
        st.subheader("History")
        stored_users = get_users()
        
        if stored_users:
            selected_obj = st.selectbox(
                "Choose a user:", 
                stored_users, 
                format_func=lambda x: x.get('user_name', 'User')
            )
            
            if st.button("Log In"):
                login_user(selected_obj['id'], selected_obj['nickname'])
        else:
            st.info("Empty")

    # 2. Create new user (with name)
    with col2:
        st.subheader("🆕 New")
        new_name_input = st.text_input("User identification")
        
        if st.button("Create"):
            if new_name_input.strip():
                new_id = str(uuid.uuid4())
                new_user(new_id, new_name_input)
                login_user(new_id, new_name_input)
            else:
                st.warning("Please type a name to save.")

    # 3. Log in anonymously
    with col3:
        st.subheader("Anonymous")
        if st.button("Log In Anonymously"):
            anon_id = str(uuid.uuid4())
            login_user(anon_id, "Anonymous Visitor")

    st.stop()

# ==========================================
# MAIN APPLICATION (CHAT)
# ==========================================

with st.sidebar:
    st.sidebar.title("Settings")
    st.write(f"**User:** {st.session_state.get('user_name', 'Unknown')}")
    st.caption(f"ID: {st.session_state['session_id']}")
    st.divider()
    if st.button("Log Out / Switch User"):
        logout()

    # Debug panel (only available in debug mode)
    if config.DEBUG_MODE:
        st.divider()
        st.session_state.debug_mode_enabled = st.toggle(
            "Debug Mode",
            value=st.session_state.get("debug_mode_enabled", True),
            key="debug_mode_toggle",
        )
        if st.session_state.debug_mode_enabled:
            render_debug_panel()

st.title(f"Hello, {st.session_state.get('user_name', '')}")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Debug state initialization
if "debug_log" not in st.session_state:
    st.session_state.debug_log = []
if "debug_session_state" not in st.session_state:
    st.session_state.debug_session_state = {}
if "debug_agent_routing" not in st.session_state:
    st.session_state.debug_agent_routing = []
if "debug_tool_calls" not in st.session_state:
    st.session_state.debug_tool_calls = []
if "debug_metrics" not in st.session_state:
    st.session_state.debug_metrics = []
if "debug_messages" not in st.session_state:
    st.session_state.debug_messages = []

# Display previous messages
for msg_idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "images" in message:
            for img in message["images"]:
                if img is not None:
                    st.image(img, use_container_width=True)
        if "videos" in message:
            for vid in message["videos"]:
                if vid is not None:
                    st.video(vid, format="video/mp4")
        if "audio" in message:
            for aud in message["audio"]:
                if aud is not None:
                    st.audio(aud, format="audio/ogg")
        if "files" in message:
            for file_idx, f in enumerate(message["files"]):
                st.download_button(
                    label=f"Download {f['name'] or 'file'}",
                    data=f["content"],
                    file_name=f["name"] or f"file_{file_idx}.pdf",
                    mime=f["mime_type"] or "application/octet-stream",
                    key=f"dl_hist_{msg_idx}_{file_idx}",
                )

# User inputs
if 'file_uploader_key' not in st.session_state:
    st.session_state.file_uploader_key = 0

files_uploaded = st.file_uploader(
    "Upload images/audio (png, jpg, mp3, etc)",
    key=f"file_uploader_{st.session_state.file_uploader_key}",
    type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4"],
    accept_multiple_files=True,
)

if "audio_uploader_key" not in st.session_state:
    st.session_state.audio_uploader_key = 0

audio_input_value = st.audio_input(
    "Record audio",
    key=f"audio_uploader_{st.session_state.audio_uploader_key}",
    )

chat_input_value = st.chat_input("Ask about pasture...")

col_btn, _ = st.columns([0.4, 0.6])
with col_btn:
    loc_input_value = st.button("Send Property Location")

user_query = None

if loc_input_value:
    user_query = """My coordinates are 2°46'32.94"S 48°31'41.74"W."""
elif chat_input_value:
    user_query = chat_input_value
elif audio_input_value:
    user_query = "[Audio received]"

def process_uploaded_files(uploaded_files) -> List[str]:
    """Saves files temporarily and returns the paths for the Agent."""
    file_paths = []
    if uploaded_files:
        for uploaded_file in uploaded_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                file_paths.append(tmp_file.name)
    return file_paths

if user_query:
    # The dev UI intentionally echoes the FULL raw input — Streamlit exists to
    # debug the pipeline, and the user's own display is not a leak surface.
    # All real protection lives inside Harness.run() (input/media/persistence
    # guardrails run before any agent or persistence). Add your own redaction
    # here if you ever deploy this webapp to end users.

    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)
        if audio_input_value:
            st.audio(audio_input_value)

    files_to_process = []
    
    if files_uploaded:
        files_to_process.extend(files_uploaded)
    if audio_input_value:
        files_to_process.append(audio_input_value)

    all_file_paths = process_uploaded_files(files_to_process)
    
    image_path = [Image(filepath=p) for p in all_file_paths if p.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    audio_path = [Audio(filepath=p, ext=p[:-4]) for p in all_file_paths if p.lower().endswith(('.wav', '.mp3', '.ogg', '.mp4'))]
    geo_files = [
        File(content=f.getvalue(), name=f.name)
        for f in (files_uploaded or [])
        if f.name.lower().endswith(('.zip', '.rar', '.kmz', '.kml', '.geojson', '.json'))
    ]

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        full_response = ""
        response = None
        audio_to_display = []
        
        try:
            run_kwargs = {
                "input": user_query,
                "user_id": st.session_state.session_id,
                "session_id": st.session_state.session_id,
                "stream": False,
            }

            if image_path:
                run_kwargs["images"] = image_path 
            if audio_path:
                run_kwargs["audio"] = audio_path
            if geo_files:
                run_kwargs["files"] = geo_files

            with st.spinner("Analyzing data and generating response..."):
                response = get_harness().run(**run_kwargs)
            
            if hasattr(response, 'content'):
                full_response = response.content
            else:
                full_response = "Error"#str(response)

            # Extract and store debug data
            try:
                debug_data = extract_workflow_debug_data(
                    response=response,
                    session_id=st.session_state.session_id,
                    user_query=user_query,
                )
                st.session_state.debug_log.append(debug_data)
                st.session_state.debug_agent_routing.extend(debug_data.get("agent_routing_trace", []))
                st.session_state.debug_tool_calls.extend(debug_data.get("tool_calls_log", []))
                st.session_state.debug_metrics.append(debug_data.get("metrics_summary", {}))
                st.session_state.debug_messages.extend(debug_data.get("message_history", []))

                # Get live session state from the agent
                try:
                    live_state = get_harness().get_session_state(
                        session_id=st.session_state.session_id
                    )
                    if live_state:
                        st.session_state.debug_session_state = extract_session_state(live_state)
                    else:
                        st.session_state.debug_session_state = debug_data.get("session_state", {})
                except Exception:
                    st.session_state.debug_session_state = debug_data.get("session_state", {})
            except Exception:
                import traceback
                traceback.print_exc()

            if response and response.images:
                for img in response.images:
                    if img.content is not None:
                        st.image(img.content, use_container_width=True)
            if response and getattr(response, 'videos', None):
                for vid in response.videos:
                    if vid.content is not None:
                        st.video(vid.content, format="video/mp4")
            audio_to_display = []
            if response and hasattr(response, 'audio') and response.audio:
                audio_to_display.extend(response.audio)
                for aud in audio_to_display:
                    if getattr(aud, 'filepath', None):
                        st.audio(str(aud.filepath), format="audio/ogg")

            if response and getattr(response, 'files', None):
                for file_idx, f in enumerate(response.files):
                    if f.content:
                        st.download_button(
                            label=f"Download {f.name or 'file'}",
                            data=f.content,
                            file_name=f.name or f"file_{file_idx}.{f.format or 'bin'}",
                            mime=f.mime_type or "application/octet-stream",
                            key=f"dl_{st.session_state.session_id}_{len(st.session_state.messages)}_{file_idx}",
                        )
            # Display the final response
            message_placeholder.markdown(full_response)

        except Exception as e:
            import traceback
            traceback.print_exc()
            st.error(f"Error processing: {e}")
            full_response = f"Sorry, an error occurred: {str(e)}"
        finally:
            for path in image_path:
                try:
                    os.remove(path)
                except:
                    pass

    if full_response:
        new_message = {"role": "assistant", "content": full_response}
        if response:
            if response.images:
                new_message["images"] = [img.content for img in response.images]
            if getattr(response, 'videos', None):
                new_message["videos"] = [
                    vid.content for vid in response.videos if vid.content
                ]
            if audio_to_display:
                new_message["audio"] = [
                    str(aud.filepath) for aud in audio_to_display if getattr(aud, 'filepath', None)
                ]
            if getattr(response, 'files', None):
                new_message["files"] = [
                    {"content": f.content, "name": f.name, "mime_type": f.mime_type}
                    for f in response.files if f.content
                ]
        
        st.session_state.messages.append(new_message)

        st.session_state.file_uploader_key += 1
        st.session_state.audio_uploader_key += 1

        st.rerun()

        