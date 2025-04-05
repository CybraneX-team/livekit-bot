import streamlit as st
import pandas as pd
import subprocess
import os
import time
from datetime import datetime
import re

# Page configuration
st.set_page_config(
    page_title="Ayurveda Clinic Voice Bot Dashboard",
    page_icon="📞",
    layout="wide"
)

# Custom CSS with improved colors
st.markdown("""
<style>
    .header {
        padding: 1.5rem 0;
        background: linear-gradient(135deg, #1a5276, #148f77);
        color: white;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .agent-status {
        font-size: 1.2rem;
        padding: 0.5rem;
        border-radius: 5px;
        text-align: center;
        margin-bottom: 1rem;
        font-weight: 500;
    }
    .agent-running {
        background-color: #27ae60;
        color: white;
    }
    .agent-stopped {
        background-color: #e74c3c;
        color: white;
    }
    .phone-number {
        font-size: 1.5rem;
        padding: 1.2rem;
        background: linear-gradient(135deg, #3498db, #2980b9);
        color: white;
        border-radius: 8px;
        text-align: center;
        margin: 1.2rem 0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    .stats-card {
        padding: 1.2rem;
        background: linear-gradient(135deg, #f5f7fa, #e8ecf1);
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        transition: transform 0.2s;
    }
    .stats-card:hover {
        transform: translateY(-5px);
    }
    .stats-card h2 {
        color: #2c3e50;
        font-weight: 600;
    }
    .stats-card h3 {
        color: #7f8c8d;
        font-weight: 500;
    }
    .stButton>button {
        background-color: #16a085;
        color: white;
        border: none;
        font-weight: 500;
    }
    .stButton>button:hover {
        background-color: #1abc9c;
    }
    div.stExpander {
        border: none;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    .expander-header {
        background-color: #f8f9fa;
        padding: 0.5rem;
        border-radius: 5px;
    }
    .user-message {
        background-color: #ebf5fb;
        border-left: 4px solid #3498db;
        padding: 0.8rem;
        margin-bottom: 0.5rem;
        border-radius: 4px;
    }
    .agent-message {
        background-color: black;
        border-left: 4px solid #27ae60;
        padding: 0.8rem;
        margin-bottom: 0.5rem;
        border-radius: 4px;
    }
    .sidebar-info {
        background-color: #f5f7fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #3498db;
    }
</style>
""", unsafe_allow_html=True)

# Helper functions
def get_transcription_files():
    """Get all transcription log files from the transcriptions folder"""
    files = []
    
    # Make sure the folder exists
    if not os.path.exists("transcriptions"):
        return files
        
    for file in os.listdir("transcriptions"):
        if file.startswith("transcriptions_") and file.endswith(".log"):
            # Extract phone number from filename
            # phone = file.replace("transcriptions_", "").replace(".log", "")
            # files.append({"file": os.path.join("transcriptions", file), "phone": phone})
            parts = file.replace(".log", "").split("_")
            if len(parts) >= 2:
                phone = parts[1]
                files.append({"file": os.path.join("transcriptions", file), "phone": phone})
    return files

def parse_log_content(content):
    """Parse log content into calls"""
    calls = []
    current_call = []
    current_timestamp = None
    
    for line in content.split('\n'):
        if line.startswith('['):
            # Extract timestamp
            timestamp_match = re.match(r'\[(.*?)\]', line)
            if timestamp_match:
                timestamp_str = timestamp_match.group(1)
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                except ValueError:
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except:
                        timestamp = None
                
                if current_timestamp is None:
                    current_timestamp = timestamp
                elif timestamp and (timestamp - current_timestamp).total_seconds() > 600:
                    # If more than 10 minutes passed, consider it a new call
                    if current_call:
                        calls.append(current_call)
                        current_call = []
                    current_timestamp = timestamp
            
            # Extract speaker and text
            if "USER:" in line:
                speaker = "User"
                text = line.split("USER:")[1].strip()
                current_call.append({"timestamp": timestamp_str if timestamp_match else "", 
                                    "speaker": speaker, 
                                    "text": text})
            elif "AGENT:" in line:
                speaker = "Agent"
                text = line.split("AGENT:")[1].strip()
                current_call.append({"timestamp": timestamp_str if timestamp_match else "", 
                                    "speaker": speaker, 
                                    "text": text})
    
    # Add the last call if it exists
    if current_call:
        calls.append(current_call)
    
    return calls

def read_transcription(file_path):
    """Read and parse a specific transcription log file"""
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return parse_log_content(content)
    except Exception as e:
        st.error(f"Error reading file {file_path}: {e}")
        return []

def read_all_transcriptions():
    """Read all transcription logs"""
    all_calls = []
    
    # Check if the transcriptions folder exists
    if not os.path.exists("transcriptions"):
        return all_calls
        
    # Read the default transcriptions.log file if it exists
    default_log = os.path.join("transcriptions", "transcriptions.log")
    if os.path.exists(default_log):
        try:
            with open(default_log, 'r', encoding='utf-8') as f:
                content = f.read()
            calls = parse_log_content(content)
            all_calls.extend(calls)
        except Exception as e:
            st.error(f"Error reading default log: {e}")
    
    # Also check for phone-specific files
    for file_info in get_transcription_files():
        calls_from_file = read_transcription(file_info["file"])
        all_calls.extend(calls_from_file)
    
    return all_calls

def start_agent():
    """Start the agent in a separate process"""
    try:
        # Assuming the actual agent script is named "agent.py" instead of trying to run paste.txt
        process = subprocess.Popen(['python', 'agent2.py', "dev"], shell=True)
        st.session_state.agent_process = process
        st.session_state.agent_running = True
        return True
    except Exception as e:
        st.error(f"Failed to start agent: {e}")
        return False

def stop_agent():
    """Stop the running agent process"""
    if 'agent_process' in st.session_state and st.session_state.agent_process:
        st.session_state.agent_process.terminate()
        st.session_state.agent_process = None
        st.session_state.agent_running = False
        return True
    return False

# Initialize session state
if 'agent_running' not in st.session_state:
    st.session_state.agent_running = False
if 'agent_process' not in st.session_state:
    st.session_state.agent_process = None

# Header
st.markdown("<div class='header'><h1 style='text-align: center;'>Dr. Ramesh's Ayurveda Clinic Voice Bot Dashboard</h1></div>", unsafe_allow_html=True)

# Control panel in sidebar
st.sidebar.title("Control Panel")

# Agent status
status_class = "agent-running" if st.session_state.agent_running else "agent-stopped"
status_text = "RUNNING" if st.session_state.agent_running else "STOPPED"
st.sidebar.markdown(f"<div class='agent-status {status_class}'>Agent Status: {status_text}</div>", unsafe_allow_html=True)

# Start/Stop buttons
col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("Start Agent", disabled=st.session_state.agent_running):
        if start_agent():
            st.sidebar.success("Agent started successfully!")
            time.sleep(1)
            st.rerun()

with col2:
    if st.button("Stop Agent", disabled=not st.session_state.agent_running):
        if stop_agent():
            st.sidebar.success("Agent stopped successfully!")
            time.sleep(1)
            st.rerun()

# Display phone number
st.markdown("<div class='phone-number'>📞 Call this number to talk to the voice bot: <b>+918035737225</b></div>", unsafe_allow_html=True)

# Dashboard stats
# Get all transcription files
transcription_files = get_transcription_files()
phone_numbers = [f["phone"] for f in transcription_files]
calls = []

# Add an option to view all calls
if phone_numbers:
    phone_options = ["All Calls"] + phone_numbers
    selected_option = st.sidebar.selectbox("Filter by Phone Number", phone_options)
    
    if selected_option == "All Calls":
        # Show all calls across all files
        calls = read_all_transcriptions()
    else:
        # Show calls for selected phone number
        selected_file = next((f["file"] for f in transcription_files if f["phone"] == selected_option), None)
        if selected_file:
            calls = read_transcription(selected_file)
else:
    st.info("No call logs found in the transcriptions folder. Start the agent and make a call to generate logs.")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(f"<div class='stats-card'><h3>Total Calls</h3><h2>{len(calls)}</h2></div>", unsafe_allow_html=True)

with col2:
    # Calculate average call duration
    total_duration = 0
    valid_calls = 0
    for call in calls:
        if len(call) >= 2:
            try:
                start_time = datetime.strptime(call[0]['timestamp'].strip(), '%Y-%m-%d %H:%M:%S.%f')
                end_time = datetime.strptime(call[-1]['timestamp'].strip(), '%Y-%m-%d %H:%M:%S.%f')
                duration = (end_time - start_time).total_seconds() / 60  # in minutes
                total_duration += duration
                valid_calls += 1
            except Exception:
                pass
    
    avg_duration = total_duration / valid_calls if valid_calls else 0
    st.markdown(f"<div class='stats-card'><h3>Avg. Call Duration</h3><h2>{avg_duration:.1f} mins</h2></div>", unsafe_allow_html=True)

with col3:
    # Count appointments made
    appointment_count = 0
    for call in calls:
        for message in call:
            if message['speaker'] == 'Agent' and 'reservation confirmed' in message['text'].lower():
                appointment_count += 1
                break
    
    st.markdown(f"<div class='stats-card'><h3>Appointments Made</h3><h2>{appointment_count}</h2></div>", unsafe_allow_html=True)

# Call logs
st.header("Call Logs")

if not calls:
    st.info("No call logs found. Start the agent and make a call to generate logs.")
else:
    # Filter options
    date_filter = st.date_input("Filter by date")
    
    # Display the call logs
    for i, call in enumerate(calls):
        # Check if we need to filter out this call
        show_call = True
        if date_filter and len(call) > 0:
            try:
                call_date = datetime.strptime(call[0]['timestamp'].strip(), '%Y-%m-%d %H:%M:%S.%f').date()
                if call_date != date_filter:
                    show_call = False
            except Exception:
                pass
        
        if show_call:
            # Format call start time for display
            try:
                call_time = datetime.strptime(call[0]['timestamp'].strip(), '%Y-%m-%d %H:%M:%S.%f')
                formatted_time = call_time.strftime("%b %d, %Y - %I:%M %p")
            except Exception:
                formatted_time = "Unknown Time"
            
            with st.expander(f"Call #{i+1} - {formatted_time}"):
                st.write("#### Transcript")
                
                for msg in call:
                    if msg['speaker'] == 'User':
                        st.markdown(f"<div class='user-message'><strong>👤 {msg['speaker']}:</strong> {msg['text']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='agent-message'><strong>🤖 {msg['speaker']}:</strong> {msg['text']}</div>", unsafe_allow_html=True)

# About section
st.sidebar.markdown("---")
st.sidebar.header("About")
st.sidebar.markdown(
    """
    <div class="sidebar-info">
    This dashboard allows you to monitor the Ayurveda Clinic Voice Bot.
    <ul>
        <li>Start/stop the voice agent</li>
        <li>View call transcriptions</li>
        <li>Monitor call statistics</li>
    </ul>
    The voice bot assists callers with information about the clinic and helps book appointments.
    </div>
    """, unsafe_allow_html=True
)