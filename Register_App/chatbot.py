import streamlit as st
import google.generativeai as genai 
import google.api_core.exceptions
import os 

# --- Configuration ---

# IMPORTANT: REPLACE THIS PLACEHOLDER WITH YOUR ACTUAL GEMINI API KEY
# A valid key is required for the application to function.
GOOGLE_API_KEY = "AIzaSyBzf7V1q3f5g_5czJDPqNiD7LpENyj6FEc" 
# Configure the Gemini client using the API key
genai.configure(api_key=GOOGLE_API_KEY)

# System Name
SYSTEM_NAME = "Office Workplace Intelligence Platform"

# Verified and Structured Knowledge Base (The core of the bot's "training")
# **This is the section you modify to "train" the bot with new facts and locations.**
SYSTEM_DATA = f"""
The bot is the {SYSTEM_NAME} Assistant, designed to help visitors navigate the premises and manage their visits efficiently.

WORKPLACE INTELLIGENCE FEATURES:

REGISTRATION & CHECK-IN:
- New visitors can register at the registration kiosk or through the web portal.
- Face recognition technology is used for secure and quick identification.
- Visitors receive a unique QR code after registration for future visits.
- Check-in is automated using facial recognition at the security gate.

VISITOR TYPES & PURPOSES:
- Meeting with Employee: Schedule meetings with specific employees.
- General Visit: Event tour, delivery, maintenance, or other purposes.
- Interview/Recruitment: For job candidates and recruitment processes.
- Vendor/Contractor: Business partners and service providers.

APPROVAL WORKFLOW:
- For employee meetings, the visitor request is sent to the host employee.
- Employees can Approve, Reject, or Reschedule the visit from their portal.
- Visitors are notified via email about the status of their visit.

CHECK-OUT & FEEDBACK:
- Check-out is also automated at the security gate.
- After check-out, visitors receive a feedback form via email.
- Feedback helps improve the visitor experience.

ADMIN FEATURES:
- Admin Dashboard for managing all visitors and employees.
- Blacklist management for security purposes.
- Analytics and reporting on visitor patterns.
- Bulk invitation system for events and meetings.

SECURITY FEATURES:
- Biometric (face) recognition for secure identification.
- Blacklist checking during check-in.
- Visit duration monitoring and alerts.
- Comprehensive visitor logs and transaction history.
"""

# --- Streamlit Setup ---
st.set_page_config(page_title=f"{SYSTEM_NAME} Assistant", page_icon="🏢")

# --- System Prompt Definition (The bot's instructions and persona) ---
SYSTEM_PROMPT = (
    f"You are the '{SYSTEM_NAME} Assistant', a highly efficient, professional, and friendly visitor assistant chatbot. "
    f"Your entire knowledge base is: {SYSTEM_DATA}. "
    "Your primary function is to answer queries related to visitor registration, check-in/check-out procedures, meeting scheduling, approval workflow, and premises navigation. "
    "You MUST ONLY use the provided knowledge base data for procedural and facility information. Do not invent details not explicitly listed. "
    "If the answer is not in the provided data, politely state that the information is not in your database and suggest contacting the reception or admin desk. "
    f"Introduce yourself as the '{SYSTEM_NAME} Assistant' and always be concise and direct in your responses."
)

# --- Chatbot Initialization ---
if "chat" not in st.session_state:
    # Using gemini-2.5-flash for stability and speed
    model = genai.GenerativeModel('gemini-2.5-flash') 

    # Start the chat and immediately send the system prompt to set the context
    st.session_state.chat = model.start_chat(history=[
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        # Internal model response to the system prompt
        {"role": "model", "parts": [{"text": "Understood. Ready to assist visitors with the Office Workplace Intelligence Platform."}]} 
    ])
    
    # Initial message for display in the chat history
    initial_greeting = f"Hello! I am the **{SYSTEM_NAME} Assistant**. I can help you with visitor registration, check-in procedures, meeting scheduling, and navigating our premises. How can I assist you today? 🏢"
    st.session_state.messages = [{"role": "assistant", "content": initial_greeting}]

# Ensure messages list is always initialized for page reloads
if "messages" not in st.session_state:
    initial_greeting = f"Hello! I am the **{SYSTEM_NAME} Assistant**. I can help you with visitor registration, check-in procedures, meeting scheduling, and navigating our premises. How can I assist you today? 🏢"
    st.session_state.messages = [{"role": "assistant", "content": initial_greeting}]


# --- Page Header ---
st.markdown(
    f"""
    <h1 style="text-align: center; color: #4361ee;">Workplace Intelligence Assistant 🏢</h1>
    <p style="text-align: center; font-size: 18px;">Your personal guide to visitor registration, check-in, and premises navigation.</p>
    <hr style="border-color: #4361ee;">
    """,
    unsafe_allow_html=True,
)

# --- Display Chat History ---
for message in st.session_state.messages:
    avatar_icon = "🤖" if message["role"] == "assistant" else "👤"
    with st.chat_message(message["role"], avatar=avatar_icon):
        st.markdown(message["content"])

# --- User Input and Response Generation ---
if prompt := st.chat_input("Ask about registration, check-in, meetings, or navigation..."):
    # 1. Add user message to state and display
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    try:
        # 2. Send user message to the Gemini API
        response = st.session_state.chat.send_message(prompt)
        
        # 3. Display assistant response
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(response.text)

        # 4. Add assistant response to state
        st.session_state.messages.append({"role": "assistant", "content": response.text})

    except google.api_core.exceptions.InvalidArgument:
        error_msg = "Error: Invalid Gemini API key or configuration issue. Please check your key and ensure it is correct."
        with st.chat_message("assistant", avatar="⚠️"):
            st.markdown(error_msg)
        st.error(error_msg)
    except Exception as e:
        error_msg = "Something went wrong with the connection to the Gemini API. Please try again later."
        with st.chat_message("assistant", avatar="⚠️"):
            st.markdown(error_msg)
        st.error(f"An unexpected error occurred: {str(e)}")
