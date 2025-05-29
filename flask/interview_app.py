from flask import Flask, request, render_template_string, jsonify, redirect, url_for, session, Response, render_template
import requests
import logging
import os
import uuid
import re
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Dial, Connect
from twilio.rest import Client
import sys
from werkzeug.exceptions import HTTPException
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from urllib.parse import quote
from flask_session import Session
import json
import websockets
import asyncio
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import base64
import gzip
import io
import PyPDF2
import filetype
from jinja2 import Template
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# HTML Templates
INDEX_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Interview App</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
    <form method="POST" enctype="multipart/form-data" class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
        <h1 class="text-3xl font-bold mb-4">Candidate Details</h1>
        <input type="text" name="name" placeholder="Candidate Name" required
            class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <input type="text" name="job_title" placeholder="Job Title" required
            class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <input type="text" name="job" placeholder="Job Description" required
            class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <input type="file" name="resume" accept=".pdf,.doc,.docx" required
            class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <button type="submit"
            class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded font-bold transition duration-300">Create Shareable Link</button>
    </form>

    <script>
        // Change input background to gray when user finishes entering (on blur)
        document.querySelectorAll('.input-field').forEach(input => {
            input.addEventListener('blur', () => {
                if (input.value || input.type === 'file') {
                    input.style.backgroundColor = '#e5e7eb'; // Tailwind's gray-200
                    input.style.color = 'black';
                }
            });
        });
    </script>
</body>
</html>
"""

INPUT_NUMBER_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Enter Phone Number</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
        <h1 class="text-3xl font-bold mb-4">Enter Number to Call</h1>
        
        <div id="interviewDetails" class="bg-gray-700 p-4 rounded-lg mb-4">
            <h2 class="text-xl font-semibold mb-2">Interview Details</h2>
            <div id="detailsContent" class="text-gray-300">
                Loading interview details...
            </div>
        </div>
        
        <form action="/initiate-vapi-call" method="POST" class="space-y-4">
            <input type="tel" name="phone_number" placeholder="Enter Phone Number (e.g., +1234567890)" required
                class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded font-bold transition duration-300">
                Call with Vapi Assistant
            </button>
        </form>
    </div>

    <script>
        // Load interview details from localStorage
        window.onload = function() {
            const detailsContent = document.getElementById('detailsContent');
            try {
                const interviewData = JSON.parse(localStorage.getItem('interviewData'));
                if (interviewData) {
                    let html = `
                        <p><strong>Name:</strong> ${interviewData.name}</p>
                        <p><strong>Job Title:</strong> ${interviewData.job_title}</p>
                        <p><strong>Position:</strong> ${interviewData.job}</p>
                    `;
                    if (interviewData.resume) {
                        html += '<p class="text-green-400">✓ Resume provided</p>';
                    } else {
                        html += '<p class="text-yellow-400">⚠ No resume provided</p>';
                    }
                    detailsContent.innerHTML = html;
                    
                    // Update session via fetch
                    fetch('/update-session', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(interviewData)
                    }).then(response => {
                        if (!response.ok) {
                            throw new Error('Failed to update session');
                        }
                        console.log('Session updated successfully');
                        // Reload the page to show updated session data
                        window.location.reload();
                    }).catch(error => {
                        console.error('Error updating session:', error);
                    });
                } else {
                    detailsContent.innerHTML = '<p class="text-red-400">No interview details found. Please start from the main page.</p>';
                }
            } catch (error) {
                console.error('Error loading interview details:', error);
                detailsContent.innerHTML = '<p class="text-red-400">Error loading interview details</p>';
            }
        };
    </script>
</body>
</html>
"""

INTERVIEW_OPTIONS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Interview Options</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
        <h1 class="text-3xl font-bold mb-4">Choose Interview Type</h1>
        <div class="space-y-4">
            <a href="/interview/instant" class="block w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-3 px-6 rounded text-center">
                Instant Interview
            </a>
            <a href="/interview/call-number" class="block w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-6 rounded text-center">
                Direct Call (Enter Number)
            </a>
        </div>
    </div>
</body>
</html>
"""

CALL_SUCCESS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Call Initiated</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
        <div class="text-center">
            <h1 class="text-3xl font-bold mb-4">Call Successfully Initiated</h1>
            <div class="bg-green-500 text-white p-4 rounded-lg mb-6">
                <p class="text-lg">Your call is being connected. Please answer your phone.</p>
            </div>
        </div>
        
        <div class="space-y-4">
            <div class="bg-gray-700 p-4 rounded-lg">
                <h2 class="text-xl font-semibold mb-2">Call Details</h2>
                <p><strong>Call ID:</strong> <span class="font-mono">{{ call_id }}</span></p>
                <p><strong>Status:</strong> <span class="text-yellow-400">{{ status }}</span></p>
                <p><strong>Destination:</strong> {{ destination_number }}</p>
            </div>
            
            <div class="bg-gray-700 p-4 rounded-lg">
                <h2 class="text-xl font-semibold mb-2">Important Notes</h2>
                <ul class="list-disc list-inside space-y-2 text-gray-300">
                    <li>Please answer your phone when it rings</li>
                    <li>Make sure you're in a quiet environment</li>
                    <li>Use headphones for better audio quality</li>
                    <li>If the call doesn't connect, please try again</li>
                </ul>
            </div>
        </div>
        
        <div class="text-center mt-6">
            <a href="/" class="text-blue-400 hover:text-blue-300">Return to Home</a>
        </div>
    </div>
</body>
</html>
"""

ERROR_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Error</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
        <h1 class="text-3xl font-bold mb-4">Error</h1>
        <div class="bg-red-500 text-white p-4 rounded-lg mb-6">
            <p class="text-lg">{{ error_message }}</p>
        </div>
        <div class="text-center mt-6">
            <a href="/" class="text-blue-400 hover:text-blue-300">Return to Home</a>
        </div>
    </div>
</body>
</html>
"""

app = Flask(__name__)

# Initialize in-memory storage for call data
call_data_store = {}

# Initialize in-memory storage for interview data
interview_data = {}

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("flask.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configure session
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_TYPE='filesystem'  # Add this line to explicitly set session type
)
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')

# Create necessary directories
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
os.makedirs(os.path.join(os.getcwd(), 'uploads'), exist_ok=True)

# Initialize session with better error handling
try:
    Session(app)
    logger.info("Session initialized successfully")
except Exception as e:
    logger.error(f"Error initializing session: {str(e)}")
    raise  # Re-raise the exception to prevent the app from running with broken sessions
    
# Add this function to help debug session issues
def debug_session():
    """Helper function to debug session state"""
    logger.debug("="*50)
    logger.debug("SESSION DEBUG")
    logger.debug("="*50)
    logger.debug(f"Session ID: {session.sid if hasattr(session, 'sid') else 'No session ID'}")
    logger.debug(f"Session Data: {dict(session)}")
    logger.debug(f"Session Cookie Name: {app.config['SESSION_COOKIE_NAME']}")
    logger.debug(f"Session File Directory: {app.config['SESSION_FILE_DIR']}")
    logger.debug("="*50)

# Use environment variables for sensitive data with defaults for development
SHARE_KEY = os.environ["VAPI_SHARE_KEY"]
PRIVATE_KEY = os.environ["VAPI_PRIVATE_KEY"]
ASSISTANT_ID = os.environ["VAPI_ASSISTANT_ID"]
VAPI_BASE_URL = os.environ["VAPI_BASE_URL"]
VAPI_WEBHOOK_URL = os.environ["VAPI_WEBHOOK_URL"]
VAPI_DESTINATION_NUMBER = os.environ["VAPI_DESTINATION_NUMBER"]

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_APP_SID = os.environ["TWILIO_APP_SID"]
TWILIO_PHONE_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]

# Add this after other Twilio credentials
TWILIO_VERIFY_SERVICE_SID = os.environ["TWILIO_VERIFY_SERVICE_SID"]

# Validate required environment variables
required_vars = {
    "VAPI_SHARE_KEY": SHARE_KEY,
    "VAPI_PRIVATE_KEY": PRIVATE_KEY,
    "VAPI_ASSISTANT_ID": ASSISTANT_ID,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_APP_SID": TWILIO_APP_SID,
    "TWILIO_PHONE_NUMBER": TWILIO_PHONE_NUMBER,
    "TWILIO_VERIFY_SERVICE_SID": TWILIO_VERIFY_SERVICE_SID
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Phone number validation regex
PHONE_REGEX = re.compile(r'^\+[1-9]\d{1,14}$')

def validate_phone_number(phone_number):
    """Validate phone number format and return cleaned number"""
    if not phone_number:
        raise ValueError("Phone number is required")
        
    # Remove any whitespace, dots, dashes or parentheses
    cleaned = re.sub(r'[\s\.\-\(\)]', '', phone_number)
    
    # Ensure number starts with + and contains only digits after
    if not PHONE_REGEX.match(cleaned):
        raise ValueError("Invalid phone number format. Must start with + followed by country code and number.")
        
    # Optional: Add additional country-specific validation here
    # For example, checking minimum/maximum length for specific country codes
    
    logger.debug(f"Validated phone number: {cleaned}")
    return cleaned

def construct_vapi_payload(interview_details, phone_number):
    """Construct payload for Vapi API call with enhanced logging and rendered prompt"""
    try:
        # Get and validate resume content
        resume_content = interview_details.get('resume_content', '')
        has_resume = bool(resume_content and len(resume_content.strip()) > 50)

        # Construct metadata with resume validation
        metadata = {
            "name": interview_details.get('name', ''),
            "position": interview_details.get('job_title', ''),
            "jobDescription": interview_details.get('job', ''),
            "resume": resume_content if has_resume else '',
            "has_resume": has_resume,
            "interviewId": interview_details.get('interview_id', '')
        }

        # Compose the system prompt directly with the resume content (no Jinja)
        if has_resume:
            rendered_prompt = f"""
You are a professional job interviewer conducting a real-time voice interview with a candidate. Your goal is to assess their qualifications, motivation, and fit for the role.

IMPORTANT - RESUME STATUS CHECK:
✓ Resume received and loaded successfully

Candidate Information:
- Name: {metadata['name']}
- Position: {metadata['position']}
- Position Description: {metadata['jobDescription']}

CANDIDATE'S CV/RESUME:
==================
{resume_content}
==================

Interview Instructions:
1. START by confirming: 'I have your resume in front of me and can see your experience in [mention 1-2 specific points]'
2. Use resume details to guide relevant questions
3. Reference specific experiences/projects from their CV
4. Assess alignment with the {metadata['position']} role

Interview Guidelines:
- Be professional and polite
- Keep responses concise and conversational
- Ask follow-up questions when needed
- Focus on both technical skills and soft skills
- End the interview professionally with next steps

Voice and Tone:
- Use a professional but friendly tone
- Speak clearly and at a moderate pace
- Maintain a natural conversation flow
- Show genuine interest in the candidate's responses

Interview Structure:
1. Introduction and rapport building
2. Experience and skills assessment
3. Technical knowledge evaluation
4. Soft skills and cultural fit assessment
5. Candidate questions and closing

End the interview by:
1. Thanking the candidate for their time
2. Providing a brief summary of what was discussed
3. Outlining next steps in the process
4. Offering to answer any questions they may have
"""
        else:
            rendered_prompt = f"""
You are a professional job interviewer conducting a real-time voice interview with a candidate. Your goal is to assess their qualifications, motivation and fit for the role.

IMPORTANT - RESUME STATUS CHECK:
⚠ No resume provided

Candidate Information:
- Name: {metadata['name']}
- Position: {metadata['position']}
- Position Description: {metadata['jobDescription']}

No resume was provided. Please:
1. Acknowledge this: 'I notice we don't have your resume on file'
2. Ask for a verbal overview of their experience
3. Take more time to establish their background

Interview Guidelines:
- Be professional and polite
- Keep responses concise and conversational
- Ask follow-up questions when needed
- Focus on both technical skills and soft skills
- End the interview professionally with next steps

Voice and Tone:
- Use a professional but friendly tone
- Speak clearly and at a moderate pace
- Maintain a natural conversation flow
- Show genuine interest in the candidate's responses

Interview Structure:
1. Introduction and rapport building
2. Experience and skills assessment
3. Technical knowledge evaluation
4. Soft skills and cultural fit assessment
5. Candidate questions and closing

End the interview by:
1. Thanking the candidate for their time
2. Providing a brief summary of what was discussed
3. Outlining next steps in the process
4. Offering to answer any questions they may have
"""
        metadata["systemPrompt"] = rendered_prompt

        # Construct full payload
        payload = {
            "assistantId": ASSISTANT_ID,
            "customer": {
                "number": phone_number
            },
            "phoneNumber": {
                "twilioPhoneNumber": TWILIO_PHONE_NUMBER,
                "twilioAccountSid": TWILIO_ACCOUNT_SID,
                "twilioAuthToken": TWILIO_AUTH_TOKEN
            },
            "metadata": metadata
        }

        logger.info("Successfully constructed Vapi payload (with direct prompt)")
        logger.info(f"Payload metadata: {json.dumps(metadata, indent=2)}")
        return payload
    except Exception as e:
        logger.error(f"Error constructing Vapi payload: {str(e)}")
        return None

# Update these constants near the top of the file
VAPI_WEBHOOK_URL = os.environ.get("VAPI_WEBHOOK_URL", "https://5f5a-2409-40f3-2d-f5a1-5924-d0c6-5897-15cc.ngrok-free.app/vapi-proxy")

def get_ngrok_url():
    """Get the current ngrok URL"""
    try:
        # Try to get the ngrok URL from environment variable first
        ngrok_url = os.environ.get("NGROK_URL")
        if ngrok_url:
            return ngrok_url

        # If not in environment, try to get it from ngrok API
        response = requests.get("http://localhost:4040/api/tunnels")
        if response.status_code == 200:
            tunnels = response.json()["tunnels"]
            for tunnel in tunnels:
                if tunnel["proto"] == "https":
                    return tunnel["public_url"]
        
        # If all else fails, return the default URL
        return "https://5f5a-2409-40f3-2d-f5a1-5924-d0c6-5897-15cc.ngrok-free.app"
    except Exception as e:
        logger.error(f"Error getting ngrok URL: {str(e)}")
        return "https://5f5a-2409-40f3-2d-f5a1-5924-d0c6-5897-15cc.ngrok-free.app"

# Update NGROK_URL to use the function
NGROK_URL = get_ngrok_url()

# Add this after other constants
ALLOWED_PHONE_NUMBERS = [
    "+916238431271",  # Your primary number
    "+919188056250"   # Your secondary number
]

# Add this after other constants
INTERVIEW_LINKS = {}  # In-memory storage for interview links

# Add this function to help with session debugging
def log_session_data():
    """Helper function to log session data"""
    logger.debug("="*50)
    logger.debug("CURRENT SESSION DATA")
    logger.debug("="*50)
    logger.debug(f"Session contents: {dict(session)}")
    logger.debug(f"Session ID: {session.sid if hasattr(session, 'sid') else 'No session ID'}")
    logger.debug(f"Session permanent: {session.permanent}")
    logger.debug("="*50)

def compress_file(file_content):
    """Compress file content using gzip"""
    try:
        if isinstance(file_content, str):
            file_content = file_content.encode('utf-8')
        elif isinstance(file_content, bytes):
            pass
        else:
            raise ValueError("Invalid file content type")
        compressed = gzip.compress(file_content)
        return base64.b64encode(compressed).decode('utf-8')
    except Exception as e:
        logger.error(f"Error compressing file: {str(e)}")
        return None

def decompress_file(compressed_content):
    """Decompress file content from gzip"""
    try:
        if not compressed_content:
            return None
        decoded = base64.b64decode(compressed_content)
        decompressed = gzip.decompress(decoded)
        try:
            # Try to decode as text first
            return decompressed.decode('utf-8')
        except UnicodeDecodeError:
            # If text decoding fails, return as base64 encoded string
            return base64.b64encode(decompressed).decode('utf-8')
    except Exception as e:
        logger.error(f"Error decompressing file: {str(e)}")
        return None

def extract_text_from_file(file_path):
    """Extract text from different file types with enhanced encoding support and better error handling"""
    try:
        logger.info(f"Attempting to extract text from file: {file_path}")
        
        # First try to detect file type
        kind = filetype.guess(file_path)
        if kind is None:
            logger.info("File type detection failed, attempting to read as text")
            # Try reading as binary first to check for BOM
            with open(file_path, 'rb') as f:
                raw = f.read(4)
                if raw.startswith(b'\xef\xbb\xbf'):  # UTF-8 BOM
                    logger.info("Detected UTF-8 BOM")
                    with open(file_path, 'r', encoding='utf-8-sig') as f:
                        return f.read()
                elif raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):  # UTF-16 BOM
                    logger.info("Detected UTF-16 BOM")
                    with open(file_path, 'r', encoding='utf-16') as f:
                        return f.read()
            
            # If no BOM detected, try multiple encodings
            encodings = ['utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'latin1', 'cp1252']
            for encoding in encodings:
                try:
                    logger.info(f"Trying to read file with {encoding} encoding")
                    with open(file_path, 'r', encoding=encoding) as f:
                        text = f.read()
                        if text.strip():  # Check if we got meaningful content
                            logger.info(f"Successfully read file with {encoding} encoding")
                            return text
                except UnicodeDecodeError:
                    logger.debug(f"Failed to decode with {encoding}")
                    continue
                except Exception as e:
                    logger.error(f"Error reading file with {encoding}: {str(e)}")
                    continue
            
            # If all text attempts fail, try PDF
            try:
                logger.info("Attempting to read as PDF")
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n";
                    if text.strip():
                        logger.info("Successfully extracted text from PDF")
                        return text
            except Exception as e:
                logger.error(f"Failed to read as PDF: {str(e)}")
            
            raise ValueError("Could not extract meaningful text from file with any supported method")
        
        mime_type = kind.mime
        logger.info(f"Detected MIME type: {mime_type}")
        
        if mime_type.startswith('text/'):
            # Handle text files with BOM detection
            with open(file_path, 'rb') as f:
                raw = f.read(4)
                if raw.startswith(b'\xef\xbb\xbf'):  # UTF-8 BOM
                    with open(file_path, 'r', encoding='utf-8-sig') as f:
                        return f.read()
                elif raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):  # UTF-16 BOM
                    with open(file_path, 'r', encoding='utf-16') as f:
                        return f.read()
            
            # Try multiple encodings for text files
            encodings = ['utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'latin1', 'cp1252']
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        text = f.read()
                        if text.strip():
                            logger.info(f"Successfully read text file with {encoding} encoding")
                            return text
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Error reading text file with {encoding}: {str(e)}")
                    continue
            
        elif mime_type == 'application/pdf':
            try:
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in pdf_reader.pages:
                        page_text = page.extract_text();
                        if page_text:
                            text += page_text + "\n";
                    if text.strip():
                        logger.info("Successfully extracted text from PDF")
                        return text;
                    else:
                        logger.warning("PDF extraction returned empty text")
            except Exception as e:
                logger.error(f"Error extracting text from PDF: {str(e)}")
        
        raise ValueError(f"Could not extract meaningful text from {mime_type} file")
            
    except Exception as e:
        logger.error(f"Error extracting text from file: {str(e)}")
        return None

def process_resume(file_path):
    """Enhanced resume processing with validation"""
    try:
        logger.info(f"Processing resume file: {file_path}")
        
        # Extract text from the file
        text = extract_text_from_file(file_path)
        if not text:
            logger.error("No text could be extracted from resume file")
            return None
            
        # Clean and validate the text
        text = text.strip()
        text = ' '.join(text.split())  # Normalize whitespace
        
        # Remove very long strings (likely binary data)
        text = ' '.join(word for word in text.split() if len(word) < 100)
        
        # Clean problematic characters
        text = text.replace('\x00', '')  # Remove null bytes
        text = re.sub(r'[^\x20-\x7E\n]', '', text)  # Remove non-printable chars
        
        # Add section markers
        text = f"""
RESUME START
===========
{text}
===========
RESUME END
"""
        
        # Validate meaningful content
        if len(text.strip()) < 50:  # Minimum meaningful length
            logger.error("Processed resume text too short to be valid")
            return None
        
        logger.info(f"Successfully processed resume ({len(text)} chars)")
        logger.info("Resume preview:")
        logger.info("-"*50)
        logger.info(text[:500] + "...")
        logger.info("-"*50)
            
        return text
        
    except Exception as e:
        logger.error(f"Resume processing error: {str(e)}")
        return None

def save_uploaded_file(file, interview_id):
    """Save uploaded file and return file info"""
    try:
        if not file:
            return None, None, None
            
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        # Create a unique filename with interview_id
        unique_filename = f"{interview_id}_{filename}"
        upload_dir = os.path.join(os.getcwd(), 'uploads')
        filepath = os.path.join(upload_dir, unique_filename)
        
        # Save the file
        file.save(filepath)
        logger.debug(f"Saved resume file to: {filepath}")
        
        # Extract and process text content
        processed_text = process_resume(filepath)
        if not processed_text:
            return None, None, None
            
        return filename, filepath, processed_text  # Return processed text directly

    except Exception as e:
        logger.error(f"Error saving uploaded file: {str(e)}")
        return None, None, None

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            # Get form data
            name = request.form.get("name")
            job_title = request.form.get("job_title")
            job = request.form.get("job")
            resume = request.files.get("resume")
            
            logger.debug("="*50)
            logger.debug("RESUME UPLOAD")
            logger.debug("="*50)
            logger.debug(f"Name: {name}")
            logger.debug(f"Job Title: {job_title}")
            logger.debug(f"Job Description: {job}")
            logger.debug(f"Resume File: {resume.filename if resume else 'No resume uploaded'}")
            
            # Generate a unique ID for this interview
            interview_id = str(uuid.uuid4())
            
            # Initialize resume data
            resume_filename = None
            resume_filepath = None
            resume_content = None
            
            # Handle resume upload if provided
            if resume:
                resume_filename, resume_filepath, resume_content = save_uploaded_file(resume, interview_id)
                if not resume_content:
                    return jsonify({"error": "Failed to process resume file"}), 500
            
            # Store interview details
            interview_details = {
                "name": name,
                "job_title": job_title,
                "job": job,
                "resume_content": resume_content,  # Store resume text directly
                "resume_filepath": resume_filepath,
                "resume_filename": resume_filename,
                "interview_id": interview_id
            }
            
            INTERVIEW_LINKS[interview_id] = interview_details
            
            logger.debug("="*50)
            logger.debug("INTERVIEW DETAILS STORED")
            logger.debug("="*50)
            logger.debug(f"Interview ID: {interview_id}")
            logger.debug(f"Name: {interview_details['name']}")
            logger.debug(f"Job Title: {interview_details['job_title']}")
            logger.debug(f"Job Description: {interview_details['job']}")
            if resume_content:
                logger.debug(f"Resume Content Length: {len(resume_content)}")
                logger.debug(f"Resume Content Preview: {resume_content[:200]}...")
            
            # Store in session
            session['interview_details'] = interview_details
            session.modified = True
            
            # Generate the interview link using NGROK_URL
            interview_link = f"{NGROK_URL}/interview/{interview_id}"
            
            # Return the HTML template with the generated link
            return render_template_string("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8" />
                    <title>Interview Link Generated</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                        <h1 class="text-3xl font-bold mb-4">Interview Link Generated</h1>
                        
                        <div class="bg-gray-700 p-4 rounded-lg">
                            <h2 class="text-xl font-semibold mb-2">Interview Details</h2>
                            <p><strong>Candidate:</strong> {{ name }}</p>
                            <p><strong>Job Title:</strong> {{ job_title }}</p>
                            <p><strong>Position:</strong> {{ job }}</p>
                        </div>
                        
                        <div class="bg-gray-700 p-4 rounded-lg">
                            <h2 class="text-xl font-semibold mb-2">Shareable Link</h2>
                            <div class="flex items-center space-x-2">
                                <input type="text" value="{{ shareable_link }}" readonly
                                    class="flex-1 p-2 rounded bg-gray-600 border border-gray-500 text-white"
                                    id="shareableLink">
                                <button onclick="copyLink()" 
                                    class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                                    Copy
                                </button>
                            </div>
                        </div>
                        
                        <div class="text-center">
                            <a href="/" class="text-blue-400 hover:text-blue-300">Create Another Link</a>
                        </div>
                    </div>
                    
                    <script>
                        function copyLink() {
                            const linkInput = document.getElementById('shareableLink');
                            linkInput.select();
                            document.execCommand('copy');
                            alert('Link copied to clipboard!');
                        }
                    </script>
                </body>
                </html>
                """, name=name, job_title=job_title, job=job, shareable_link=interview_link)
            
        except Exception as e:
            logger.error(f"Error in index route: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return jsonify({"error": str(e)}), 500
    return render_template_string(INDEX_PAGE)

@app.route("/interview", methods=["GET"])
def interview_home():
    """Redirect to interview options"""
    return redirect(url_for('interview_options'))

@app.route("/interview/options", methods=["GET"])
def interview_options():
    """Show interview options"""
    return render_template_string(INTERVIEW_OPTIONS_PAGE)

@app.route("/interview/instant", methods=["GET"])
def instant_interview():
    """Start an instant interview"""
    interview_details = session.get('interview_details', {})
    if not interview_details:
        return redirect(url_for('index'))
    
    # Get the interview ID from the session
    interview_id = interview_details.get('interview_id')
    if not interview_id:
        return redirect(url_for('index'))
    
    # Always provide defined values for resume_content and has_resume
    resume_content = interview_details.get('resume_content', '') or ''
    has_resume = bool(resume_content)

    return render_template_string(
        INTERVIEW_PAGE,
        name=interview_details.get('name', ''),
        job_title=interview_details.get('job_title', ''),
        job=interview_details.get('job', ''),
        interview_id=interview_id,
        interview_details=interview_details,
        resume_content=resume_content,
        has_resume=has_resume,
        SHARE_KEY=SHARE_KEY,
        ASSISTANT_ID=ASSISTANT_ID
    )

@app.route("/interview/call-number", methods=["GET"])
def call_number():
    """Show the page for entering phone number"""
    # Debug session state
    debug_session()
    
    # Get interview details from session
    interview_details = session.get('interview_details', {})
    
    # Log the session data for debugging
    logger.debug("="*50)
    logger.debug("CALL NUMBER ROUTE - SESSION DATA")
    logger.debug("="*50)
    logger.debug(f"Interview Details: {interview_details}")
    
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <title>Enter Phone Number</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
            <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                <h1 class="text-3xl font-bold mb-4">Enter Number to Call</h1>
                
                <div id="interviewDetails" class="bg-gray-700 p-4 rounded-lg mb-4">
                    <h2 class="text-xl font-semibold mb-2">Interview Details</h2>
                    <div id="detailsContent" class="text-gray-300">
                        {% if interview_details %}
                            <p><strong>Name:</strong> {{ interview_details.get('name', 'Not found') }}</p>
                            <p><strong>Job Title:</strong> {{ interview_details.get('job_title', 'Not found') }}</p>
                            <p><strong>Position:</strong> {{ interview_details.get('job', 'Not found') }}</p>
                            {% if interview_details.get('resume_content') %}
                                <p class="text-green-400">✓ Resume provided</p>
                            {% else %}
                                <p class="text-yellow-400">⚠ No resume provided</p>
                            {% endif %}
                        {% else %}
                            Loading interview details...
                        {% endif %}
                    </div>
                </div>
                
                <form action="/initiate-vapi-call" method="POST" class="space-y-4">
                    <input type="tel" name="phone_number" placeholder="Enter Phone Number (e.g., +1234567890)" required
                        class="input-field w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded font-bold transition duration-300">
                        Call with Vapi Assistant
                    </button>
                </form>
            </div>

            <script>
                // Load interview details from localStorage as backup
                window.onload = function() {
                    const detailsContent = document.getElementById('detailsContent');
                    {% if not interview_details %}
                        try {
                            const interviewData = JSON.parse(localStorage.getItem('interviewData'));
                            if (interviewData) {
                                let html = `
                                    <p><strong>Name:</strong> ${interviewData.name}</p>
                                    <p><strong>Job Title:</strong> ${interviewData.job_title}</p>
                                    <p><strong>Position:</strong> ${interviewData.job}</p>
                                `;
                                if (interviewData.resume) {
                                    html += '<p class="text-green-400">✓ Resume provided</p>';
                                } else {
                                    html += '<p class="text-yellow-400">⚠ No resume provided</p>';
                                }
                                detailsContent.innerHTML = html;
                                
                                // Update session via fetch
                                fetch('/update-session', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(interviewData)
                                }).then(response => {
                                    if (!response.ok) {
                                        throw new Error('Failed to update session');
                                    }
                                    console.log('Session updated successfully');
                                    // Reload the page to show updated session data
                                    window.location.reload();
                                }).catch(error => {
                                    console.error('Error updating session:', error);
                                });
                            } else {
                                detailsContent.innerHTML = '<p class="text-red-400">No interview details found. Please start from the main page.</p>';
                            }
                        } catch (error) {
                            console.error('Error loading interview details:', error);
                            detailsContent.innerHTML = '<p class="text-red-400">Error loading interview details</p>';
                        }
                    {% endif %}
                };
            </script>
        </body>
        </html>
    """, interview_details=interview_details)

@app.route("/vapi-proxy", methods=["POST"])
@limiter.limit("100 per minute")
def vapi_proxy():
    """Handle incoming Vapi webhook requests or proxy outbound Vapi API calls."""
    try:
        # Log the raw request data
        logger.info("="*50)
        logger.info("VAPI WEBHOOK REQUEST RECEIVED")
        logger.info("="*50)
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request method: {request.method}")
        logger.info(f"Request content type: {request.content_type}")
        
        data = request.get_json()
        if not data:
            logger.error("No JSON data provided to vapi-proxy")
            return jsonify({"error": "No JSON data provided"}), 400
            
        logger.info(f"Raw webhook payload: {json.dumps(data, indent=2)}")

        # --- Handle Vapi Webhook Events ---
        # Vapi sends a payload with 'message', 'call', 'assistant' keys for certain events like 'assistant-request'
        if "message" in data and "call" in data and "assistant" in data:
            logger.info("Received webhook data with message, call, and assistant keys.")
            message_type = data.get("message", {}).get("type")
            call_data_from_vapi = data.get("call", {})
            metadata = call_data_from_vapi.get("metadata", {})
            interview_id = metadata.get("interviewId")

            logger.info(f"Webhook message type: {message_type}")
            logger.info(f"Webhook interview ID: {interview_id}")
            logger.info(f"Webhook metadata: {json.dumps(metadata, indent=2)}")

            # Assuming 'assistant-request' is the primary event needing dynamic config
            if message_type == "assistant-request" and interview_id:
                logger.info(f"Handling assistant-request webhook for interview ID: {interview_id}")
                if interview_id in INTERVIEW_LINKS:
                    interview_details = INTERVIEW_LINKS[interview_id]
                    logger.info(f"Found interview details for ID {interview_id}")
                    logger.info(f"Interview details: {json.dumps(interview_details, indent=2)}")

                    name = interview_details.get('name', '')
                    position = interview_details.get('job_title', '')
                    job_desc = interview_details.get('job', '')
                    resume_content = interview_details.get('resume_content', '')
                    has_resume = bool(resume_content and len(resume_content.strip()) > 50)

                    logger.info(f"Resume status: {'Present' if has_resume else 'Missing'}")
                    if has_resume:
                        logger.info(f"Resume content length: {len(resume_content)}")
                        logger.info(f"Resume preview: {resume_content[:200]}...")

                    # Construct the dynamic system prompt
                    if has_resume:
                        system_prompt_content = f"""You are a professional job interviewer conducting a real-time voice interview with a candidate for the {position} role. Your primary goal is to assess their qualifications, motivation, and fit for this role by asking questions based on their provided CV/Resume and the job description.

Candidate Information:
- Name: {name}
- Position: {position}
- Position Description: {job_desc}

CANDIDATE'S CV:
==================
{resume_content}
==================

Interview Instructions:
1. Greet the candidate by name warmly and professionally.
2. Immediately transition to the first interview question by referencing a specific piece of experience, skill, or education mentioned in their CV/Resume that is relevant to the {position} role. Make it clear you are asking based on their CV.
3. Throughout the interview, formulate questions by referring directly to the candidate's CV and the job description. Use question types like:\n- 'I noticed you worked with [Technology/Tool] at [Company]. Can you tell me about a specific project where you used it and your role in that project?'\n- 'Your experience at [Previous Company] seems relevant to this role. What were your main responsibilities and what results did you achieve?'\n- 'I see you have experience with [Specific Skill]. Can you share an example of how you applied this skill in a challenging situation?'\n- 'Your background in [Field/Area] is interesting. How has this experience prepared you for the challenges in this role?'\n- 'The job requires expertise in [Required Skill]. Based on your experience at [Company], how would you approach [Specific Task]?'
4. Listen actively to the candidate's responses and ask follow-up questions that connect their answers back to their resume details and the job requirements.
5. **If the candidate asks a direct factual question and the answer is available in the provided CV/Resume or the initial context you have (like their name or the job title), answer their question concisely and then smoothly transition back to your interview questions.** Do NOT say there will be time for questions later if you can answer it now based on the provided information.
6. Assess the candidate's alignment with the {position} role based on their CV and responses.

Interview Guidelines:
- Maintain a professional, friendly, and conversational tone throughout.
- Be polite and encouraging.
- Ensure your questions are clear and directly related to the CV content or the job description.
- Keep your own responses concise and natural.
- Focus on assessing both technical skills and soft skills relevant to the {position} role.
- Manage the flow of the conversation based on the candidate's responses, the points you need to cover from the CV/job description, and any questions they ask.

Interview Structure:
1. Start: Greet the candidate by name and immediately ask your first question based on their CV.
2. Core: Conduct the main interview, asking detailed, CV-based questions, listening to answers, asking follow-ups, and answering candidate's direct factual questions when possible based on provided information.
3. Closing: Thank the candidate, briefly summarize the topics discussed (referencing their experience), outline next steps, and explicitly offer them a dedicated time to ask any remaining questions.

End the interview by:
1. Thanking the candidate for their time.
2. Providing a brief summary of what was discussed.
3. Outlining next steps in the process.
4. Explicitly opening the floor for *any* questions they may have that weren't addressed earlier.
"""
                    else:
                        system_prompt_content = f"""You are a professional job interviewer conducting a real-time voice interview with a candidate for the {position} role. Your primary goal is to assess their qualifications, motivation, and fit for this role by asking questions.

Candidate Information:
- Name: {name}
- Position: {position}
- Position Description: {job_desc}

No resume was provided. Please:
1. Greet the candidate by name warmly and professionally.
2. Acknowledge that you do not have their resume on file: "I notice we don't have your resume on file."
3. Ask for a verbal overview of their experience and background relevant to the {position} role.
4. Take sufficient time to establish their background through their verbal responses.
5. **If the candidate asks a direct factual question and the answer is available in the initial context you have (like their name or the job title), answer their question concisely and then smoothly transition back to your interview questions.** Do NOT say there will be time for questions later if you can answer it now based on the provided information.
6. Assess the candidate's alignment with the {position} role based on their verbal responses and the job description.

Interview Guidelines:
- Maintain a professional, friendly, and conversational tone throughout.
- Be polite and encouraging.
- Ensure your questions are clear and relevant to the job description.
- Keep your own responses concise and natural.
- Focus on assessing both technical skills and soft skills relevant to the {position} role.
- Manage the flow of the conversation based on the candidate's responses and any questions they ask.

Interview Structure:
1. Start: Greet the candidate by name and acknowledge no resume is on file, then ask for their verbal overview.
2. Core: Conduct the main interview based on their verbal overview and the job description, asking follow-ups, and answering candidate's direct factual questions when possible based on provided information.
3. Closing: Thank the candidate, briefly summarize the topics discussed, outline next steps, and explicitly offer them a dedicated time to ask any remaining questions.

End the interview by:
1. Thanking the candidate for their time.
2. Providing a brief summary of what was discussed.
3. Outlining next steps in the process.
4. Explicitly opening the floor for *any* questions they may have that weren't addressed earlier.
"""

                    # Return the assistant configuration to Vapi
                    assistant_config = {
                        "model": {
                            "provider": "anthropic",
                            "model": "claude-3-opus-20240229",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": system_prompt_content
                                }
                            ]
                        },
                        "voice": {
                            "provider": "azure",
                            "voiceId": "andrew"
                        },
                        "firstMessage": f"Hello {name}! I'm your AI interviewer for the {position} position. Are you ready to begin the interview?",
                        "endCallFunctionEnabled": True
                    }
                    logger.info("Returning dynamic assistant configuration to Vapi webhook")
                    logger.info(f"Assistant config: {json.dumps(assistant_config, indent=2)}")
                    return jsonify({"assistant": assistant_config}), 200

                else:
                    logger.warning(f"Interview details not found in INTERVIEW_LINKS for ID {interview_id}")
                    return jsonify({"error": "Interview details not found"}), 404
            elif message_type:
                logger.info(f"Acknowledging Vapi webhook event type: {message_type}")
                return jsonify({"status": "received", "event_type": message_type}), 200
            else:
                logger.warning("Received webhook data without a message type or interview ID")
                return jsonify({"error": "Invalid webhook data format"}), 400

        # --- Handle Outbound Proxy Calls (Existing Logic) ---
        if "endpoint" in data and "method" in data:
            endpoint = data.get("endpoint")
            method = data.get("method", "POST")
            payload = data.get("payload", {})
        
            # Defensive fix: Remove any top-level 'message' property if present in old payloads
            # This check is primarily for legacy or malformed data from the app side,
            # not the Vapi webhook structure we just handled.
        if "message" in payload:
                 logger.warning("Removing unexpected 'message' property from Vapi outbound payload")
        del payload["message"]

        headers = {
            "Authorization": f"Bearer {PRIVATE_KEY}", # Use PRIVATE_KEY for server-side API calls
            "Content-Type": "application/json"
        }
        
        # Validate and construct target URL
        if not endpoint.startswith('/'):
            return jsonify({"error": "Invalid endpoint format"}), 400
        
        target_url = f"{VAPI_BASE_URL}{endpoint}"

        logger.debug(f"Proxy forwarding outbound request to URL: {target_url}")
        logger.debug(f"Proxy forwarding outbound payload: {json.dumps(payload, indent=2)}")
        
        # Make the request to Vapi
        response = requests.request(
            method=method,
            url=target_url,
            json=payload,
            headers=headers,
            timeout=30  # Add timeout
        )
        
        # Log the response for debugging
        logger.debug(f"Vapi outbound response status: {response.status_code}")
        logger.debug(f"Vapi outbound response body: {response.text}")
        
        # Raise HTTPError for bad responses (4xx or 5xx)
        response.raise_for_status()

        # Check if it's a successful response and return JSON
        response_data = response.json() if response.text else {}

        # For the new /call endpoint with websocket transport, extract websocketCallUrl
            # This part is for when your app initiates a call directly via the proxy,
            # not the webhook flow.
        if endpoint == '/call' and response.status_code in [200, 201]:
             websocket_url = response_data.get('transport', {}).get('websocketCallUrl')
             if websocket_url:
                  logger.debug(f"Extracted Vapi websocketCallUrl: {websocket_url}")
                    # Store this URL with the call SID for later use in the /voice endpoint
        call_sid = response_data.get('phoneCall', {}).get('providerId') # Assuming Twilio SID
        if call_sid:
                        # Need to store interview details and websocket URL by call SID
                        # This requires getting the interview_id from the original initiate-vapi-call request
                        # For now, let's just store the URL
                        call_data_store[call_sid] = call_data_store.get(call_sid, {}) # Ensure dict exists
                        call_data_store[call_sid]['vapi_websocket_url'] = websocket_url
                        logger.debug(f"Stored websocket URL for call SID: {call_sid}")
        else:
                        logger.warning("Could not extract call SID from Vapi response to store websocket URL.")


        return jsonify(response_data), response.status_code
        
        # If data is not a known webhook type and not an outbound proxy request
        logger.error("Received unrecognized data structure in vapi-proxy")
        return jsonify({"error": "Unrecognized request format"}), 400
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error in vapi-proxy: {str(e)}")
        # Attempt to extract more specific error info if available
        try:
            error_response = e.response.json() if e.response else {}
            error_message = error_response.get('message', str(e))
            error_details = error_response.get('details', '')
            logger.error(f"Vapi Proxy Network Error Details: {error_details}")
        except:
            error_message = str(e)
            error_details = ''

        return jsonify({
            "error": "Failed to communicate with Vapi service or process request",
            "details": error_message
        }), e.response.status_code if e.response is not None else 503
    except Exception as e:
        logger.error(f"Proxy error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "error": "Internal server error processing proxy request",
            "details": str(e)
        }), 500

@app.route("/vapi_test", methods=["GET", "POST"])
def vapi_test():
    web_call_url = ""
    if request.method == "POST":
        headers = {
            "Authorization": f"Bearer {SHARE_KEY}",
            "Content-Type": "application/json"
        }
        body = {
            "assistantId": ASSISTANT_ID
        }
        try:
            response = requests.post(f"{VAPI_BASE_URL}/call/web", headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            web_call_url = data.get("webCallUrl", "No URL returned")
        except Exception as e:
            web_call_url = f"Error: {e}"
    return render_template_string("""
        <html>
        <head><title>Test Vapi Assistant</title></head>
        <body style="font-family:sans-serif; padding: 40px;">
            <h2>🎙️ Vapi Voice Assistant Test</h2>
            <form method="post">
                <button type="submit">Start Call</button>
            </form>
            {% if web_call_url %}
                <p><strong>Call URL:</strong> <a href="{{ web_call_url }}" target="_blank">{{ web_call_url }}</a></p>
            {% endif %}
        </body>
        </html>
    """, web_call_url=web_call_url)

@app.route("/vapi_widget")
def vapi_widget():
    return render_template_string(f"""
        <html>
        <head>
            <title>Test Vapi Assistant Widget</title>
        </head>
        <body style="font-family:sans-serif; padding: 40px;">
            <h2>🎙️ Vapi Voice Assistant Widget Test</h2>
            <!-- Vapi Widget will appear here -->
            <script>
                var vapiInstance = null;
                const assistant = '{ASSISTANT_ID}'; // Your assistant ID
                const apiKey = '{SHARE_KEY}'; // Your Public key from Vapi Dashboard
                const buttonConfig = {{}}; // Optional configuration

                (function (d, t) {{
                  var g = document.createElement(t),
                    s = d.getElementsByTagName(t)[0];
                  g.src =
                    "https://cdn.jsdelivr.net/gh/VapiAI/html-script-tag@latest/dist/assets/index.js";
                  g.defer = true;
                  g.async = true;
                  s.parentNode.insertBefore(g, s);

                  g.onload = function () {{
                    vapiInstance = window.vapiSDK.run({{
                      apiKey: apiKey,
                      assistant: assistant,
                      config: buttonConfig,
                    }});
                  }};
                }})(document, "script");
            </script>
        </body>
        </html>
    """)

@app.route("/proxy/<call_sid>", methods=['POST'])
def proxy_websocket(call_sid):
    """Proxy endpoint for WebSocket connection"""
    # Get the Vapi websocketCallUrl from the in-memory store
    call_data = call_data_store.get(call_sid)
    vapi_websocket_url = call_data.get('vapi_websocket_url') if call_data else None

    if not vapi_websocket_url:
        logger.error(f"WebSocket URL not found for call SID: {call_sid}")
        return Response("WebSocket URL not found", status=404)

    async def handle_websocket():
        # vapi_websocket_url is guaranteed to be not None here
        websocket = None
        try:
            websocket = await websockets.connect(
                vapi_websocket_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=20,
                max_size=None,
                extra_headers={
                    'User-Agent': 'Twilio/1.0',
                    'Origin': 'https://api.twilio.com'
                }
            )
            logger.info(f"Successfully connected to WebSocket for call SID: {call_sid}")

            while True:
                try:
                    data = await websocket.recv();
                    if data:
                        yield data
                except websockets.exceptions.ConnectionClosed as e:
                    logger.info(f"WebSocket connection closed for call SID: {call_sid}, code: {e.code}, reason: {e.reason}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving data from WebSocket: {str(e)}")
                    break
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {str(e)}")
        finally:
            if websocket:
                try:
                    await websocket.close()
                except Exception as e:
                    logger.error(f"Error closing WebSocket: {str(e)}")

    def generate():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            for chunk in loop.run_until_complete(handle_websocket()):
                yield chunk
        except Exception as e:
            logger.error(f"Error in generate function: {str(e)}")

    return Response(
        generate(),
        mimetype='audio/x-mulaw',
        headers={
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route("/voice", methods=['POST'])
def voice():
    """TwiML endpoint for voice calls"""
    try:
        logger.debug("="*50)
        logger.debug("VOICE ENDPOINT CALLED")
        logger.debug("="*50)
        
        # Log session data at the start of the voice endpoint
        log_session_data()
        
        logger.debug(f"Request headers: {dict(request.headers)}")
        logger.debug("Fetching TwiML for incoming call.")
        logger.debug(f"Request form data: {request.form}")
        
        response = VoiceResponse()
        
        # Get the Twilio Call SID from the request form data
        twilio_call_sid = request.form.get('CallSid')
        logger.debug(f"Retrieved Twilio Call SID from request: {twilio_call_sid}")
        
        if not twilio_call_sid:
            logger.error("Twilio Call SID not found in request form data.")
            response.say("We encountered an issue setting up the call. Please try again.", voice='Polly.Joanna')
            response.hangup()
            return str(response)

        # Get the Vapi WebSocket URL from the in-memory store
        call_data = call_data_store.get(twilio_call_sid)
        logger.debug(f"Retrieved call data from store: {call_data}")
        
        if not call_data:
            logger.error(f"No call data found for SID: {twilio_call_sid}")
            response.say("We encountered an issue connecting to the assistant. Please try again.", voice='Polly.Joanna')
            response.hangup()
            return str(response)
            
        vapi_websocket_url = call_data.get('vapi_websocket_url')
        if not vapi_websocket_url:
            logger.error(f"No WebSocket URL in call data for SID: {twilio_call_sid}")
            response.say("We encountered an issue connecting to the assistant. Please try again.", voice='Polly.Joanna')
            response.hangup()
            return str(response)

        logger.debug(f"Retrieved Vapi WebSocket URL from store: {vapi_websocket_url}")

        # First say the greeting with a longer pause
        response.say("Connecting to your Vapi assistant. Please hold.", voice='Polly.Joanna')
        response.pause(length=2)
        
        # Create a Connect object with Stream for Vapi
        connect = Connect()
        connect.stream(
            name="vapi_stream",
            track="inbound_track",
            url=vapi_websocket_url
        )
        response.append(connect)
        
        logger.debug("Generated TwiML response:")
        logger.debug(str(response))
        return str(response)
        
    except Exception as e:
        logger.error(f"Error in voice endpoint: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return a graceful error response
        response = VoiceResponse()
        response.say("We're experiencing technical difficulties. Please try again.", voice='Polly.Joanna')
        response.hangup()
        return str(response)

@app.route("/handle-extension", methods=['POST'])
@limiter.limit("20 per minute")
def handle_extension():
    """Handle the extension selection"""
    try:
        digits = request.values.get('Digits', '')
        if not digits:
            return jsonify({"error": "No digits provided"}), 400
        
        response = VoiceResponse()
        
        if digits == '1':
            try:
                validate_phone_number(VAPI_DESTINATION_NUMBER)
                response.say('Connecting to extension 1.', voice='alice')
                dial = Dial(caller_id=TWILIO_PHONE_NUMBER)
                dial.number(VAPI_DESTINATION_NUMBER)
                response.append(dial)
            except ValueError as e:
                response.say('Invalid phone number configuration for extension 1.', voice='alice')
                logger.error(f"Invalid phone number for extension 1: {VAPI_DESTINATION_NUMBER} - {e}")
                response.hangup()
        elif digits == '2':
            try:
                validate_phone_number("+919188056250")  # Second extension
                response.say('Connecting to extension 2.', voice='alice')
                dial = Dial(caller_id=TWILIO_PHONE_NUMBER)
                dial.number("+919188056250")
                response.append(dial)
            except ValueError as e:
                response.say('Invalid phone number configuration for extension 2.', voice='alice')
                logger.error(f"Invalid phone number for extension 2: +919188056250 - {e}")
                response.hangup()
        else:
            response.say('Invalid selection. Please try again.', voice='alice')
            response.redirect('/voice')
        
        return str(response)
        
    except Exception as e:
        logger.error(f"Error in handle-extension endpoint: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        response = VoiceResponse()
        response.say('An error occurred. Please try again later.', voice='alice')
        response.hangup()
        return str(response)

@app.route("/interview/call", methods=["GET", "POST"])
def call_interview():
    """Handle call-based interviews"""
    if request.method == "POST":
        phone_number = request.form.get("phone_number")
        if not phone_number:
            return jsonify({"error": "Phone number is required"}), 400
            
        try:
            validate_phone_number(phone_number)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
            
        # Store the phone number in session
        session['interview_phone'] = phone_number
        return redirect(url_for('interview_options'))
        
    return render_template_string(INPUT_NUMBER_PAGE)

@app.route("/verify-number", methods=["GET", "POST"])
def verify_number():
    """Handle phone number verification"""
    if request.method == "POST":
        phone_number = request.form.get("phone_number")
        if not phone_number:
            return jsonify({"error": "Phone number is required"}), 400
            
        try:
            validate_phone_number(phone_number)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
            
        # Check if the number is in the allowed list
        if phone_number not in ALLOWED_PHONE_NUMBERS:
            return render_template_string("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8" />
                    <title>Invalid Phone Number</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg text-center">
                        <h1 class="text-3xl font-bold mb-4">Invalid Phone Number</h1>
                        <p class="text-gray-400 mb-6">Please use one of the following numbers:</p>
                        <ul class="text-gray-300 mb-6">
                            {% for number in allowed_numbers %}
                            <li class="mb-2">{{ number }}</li>
                            {% endfor %}
                        </ul>
                        <a href="/verify-number" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                            Try Again
                        </a>
                    </div>
                </body>
                </html>
            """, allowed_numbers=ALLOWED_PHONE_NUMBERS)
            
        try:
            # Debug logging for Twilio configuration
            logger.debug("="*50)
            logger.debug("TWILIO VERIFICATION CONFIGURATION")
            logger.debug("="*50)
            logger.debug(f"Account SID: {TWILIO_ACCOUNT_SID}")
            logger.debug(f"Auth Token: {TWILIO_AUTH_TOKEN[:5]}...")
            logger.debug(f"Verify Service SID: {TWILIO_VERIFY_SERVICE_SID}")
            logger.debug(f"Phone Number to verify: {phone_number}")
            
            # First, check if the number is already verified
            try:
                verification_checks = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verification_checks.list(
                    to=phone_number
                )
                logger.debug(f"Existing verifications: {verification_checks}")
                
                # If the number is already verified, skip to the next step
                if any(check.status == 'approved' for check in verification_checks):
                    logger.debug("Number is already verified, proceeding to call initiation")
                    session['verified_number'] = phone_number
                    return redirect(url_for('initiate_vapi_call'))
            except Exception as e:
                logger.debug(f"Error checking existing verifications: {str(e)}")
            
            # If not verified, proceed with verification
            logger.debug("Initiating new verification...")
            verification = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verifications.create(
                to=phone_number,
                channel='sms'
            )
            
            logger.debug(f"Verification created: {verification.status}")
            
            # Store the phone number in session for verification
            session['pending_verification'] = {
                'phone_number': phone_number,
                'status': verification.status
            }
            
            return render_template_string("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8" />
                    <title>Verify Phone Number</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                        <h1 class="text-3xl font-bold mb-4">Verify Your Phone Number</h1>
                        <p class="text-gray-400 mb-6">We've sent a verification code to {{ phone_number }}. Please enter it below:</p>
                        
                        <form action="/confirm-verification" method="POST" class="space-y-4">
                            <input type="hidden" name="phone_number" value="{{ phone_number }}">
                            <input type="text" name="verification_code" placeholder="Enter verification code" required
                                class="w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500">
                            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded font-bold transition duration-300">
                                Verify Number
                            </button>
                        </form>
                    </div>
                </body>
                </html>
            """, phone_number=phone_number)
            
        except Exception as e:
            logger.error(f"Failed to send verification code: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Check if it's an unverified number error
            if "unverified" in str(e).lower():
                # Try to get more information about the error
                try:
                    # Check if the number is actually verified in Twilio
                    verified_numbers = twilio_client.outgoing_caller_ids.list()
                    is_verified = any(number.phone_number == phone_number for number in verified_numbers)
                    logger.debug(f"Number {phone_number} verified status: {is_verified}")
                    
                    if is_verified:
                        # If the number is verified but we're still getting the error,
                        # try to proceed with call initiation
                        logger.debug("Number is verified in Twilio, proceeding to call initiation")
                        session['verified_number'] = phone_number
                        return redirect(url_for('initiate_vapi_call'))
                except Exception as check_error:
                    logger.error(f"Error checking verified numbers: {str(check_error)}")
            
            return render_template_string("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8" />
                    <title>Phone Number Verification Required</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                        <h1 class="text-3xl font-bold mb-4">Phone Number Verification Required</h1>
                        <div class="bg-yellow-500 text-white p-4 rounded-lg mb-6">
                            <p class="text-lg">Your phone number needs to be verified in Twilio first.</p>
                        </div>
                        
                        <div class="space-y-4">
                            <h2 class="text-xl font-semibold">Steps to Verify Your Number:</h2>
                            <ol class="list-decimal list-inside space-y-2 text-gray-300">
                                <li>Go to <a href="https://console.twilio.com/us1/develop/phone-numbers/manage/verified" target="_blank" class="text-blue-400 hover:text-blue-300">Twilio Console</a></li>
                                <li>Click "Add a new Caller ID"</li>
                                <li>Enter your phone number: <span class="font-mono">{{ phone_number }}</span></li>
                                <li>Choose "Call me with a code" or "Text me a code"</li>
                                <li>Enter the verification code you receive</li>
                            </ol>
                            
                            <p class="text-gray-400 mt-4">Once your number is verified, come back and try again.</p>
                        </div>
                        
                        <div class="text-center mt-6">
                            <a href="/verify-number" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                                Try Again
                            </a>
                        </div>
                    </div>
                </body>
                </html>
            """, phone_number=phone_number)
            
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <title>Verify Phone Number</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
            <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                <h1 class="text-3xl font-bold mb-4">Verify Your Phone Number</h1>
                <p class="text-gray-400 mb-6">Please enter one of the following numbers to receive a verification code:</p>
                <ul class="text-gray-300 mb-6">
                    {% for number in allowed_numbers %}
                    <li class="mb-2">{{ number }}</li>
                    {% endfor %}
                </ul>
                
                <form action="/verify-number" method="POST" class="space-y-4">
                    <input type="tel" name="phone_number" placeholder="Enter Phone Number (e.g., +1234567890)" required
                        class="w-full p-3 rounded bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded font-bold transition duration-300">
                        Send Verification Code
                    </button>
                </form>
            </div>
        </body>
        </html>
    """, allowed_numbers=ALLOWED_PHONE_NUMBERS)

@app.route("/confirm-verification", methods=["POST"])
def confirm_verification():
    """Handle verification code confirmation"""
    phone_number = request.form.get("phone_number")
    verification_code = request.form.get("verification_code")
    
    if not phone_number or not verification_code:
        return jsonify({"error": "Phone number and verification code are required"}), 400
        
    try:
        # Check the verification code
        verification_check = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verification_checks.create(
            to=phone_number,
            code=verification_code
        )
        
        if verification_check.status == 'approved':
            # Store the verified number in session
            session['verified_number'] = phone_number
            return redirect(url_for('initiate_vapi_call'))
        else:
            return render_template_string("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8" />
                    <title>Verification Failed</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                    <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg text-center">
                        <h1 class="text-3xl font-bold mb-4">Verification Failed</h1>
                        <p class="text-gray-400 mb-6">The verification code was incorrect. Please try again.</p>
                        <a href="/verify-number" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                            Try Again
                        </a>
                    </div>
                </body>
                </html>
            """)
            
    except Exception as e:
        logger.error(f"Failed to verify code: {str(e)}")
        return jsonify({
            "error": "Failed to verify code",
            "details": str(e)
        }), 500

@app.route("/initiate-vapi-call", methods=["POST"])
@limiter.limit("10 per minute")
def initiate_vapi_call():
    try:
        # Get and validate phone number
        phone_number = request.form.get("phone_number")
        if not phone_number:
            return jsonify({"error": "Phone number is required"}), 400

        try:
            validate_phone_number(phone_number)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # Get interview details with logging
        interview_details = session.get('interview_details', {})
        logger.info("="*50)
        logger.info("INITIATE VAPI CALL - INTERVIEW DETAILS CHECK")
        logger.info("="*50)
        logger.info(f"Interview details found in session: {bool(interview_details)}")
        logger.debug(f"Interview details from session: {interview_details}")

        interview_id = interview_details.get('interview_id')
        if not interview_id:
             logger.error("Interview ID not found in session interview_details.")
             return jsonify({"error": "Interview details or ID not found in session"}), 400

        # --- Construct the dynamic assistant configuration with resume ---
        name = interview_details.get('name', '')
        position = interview_details.get('job_title', '')
        job_desc = interview_details.get('job', '')
        resume_content = interview_details.get('resume_content', '')
        has_resume = bool(resume_content and len(resume_content.strip()) > 50)

        # Construct the dynamic system prompt (same logic as in vapi_proxy)
        if has_resume:
            system_prompt_content = f"""You are a professional job interviewer conducting a real-time voice interview with a candidate for the {position} role. Your primary goal is to assess their qualifications, motivation, and fit for this role by asking questions based on their provided CV/Resume and the job description.

Candidate Information:
- Name: {name}
- Position: {position}
- Position Description: {job_desc}

CANDIDATE'S CV:
==================
{resume_content}
==================

Interview Instructions:
1. Greet the candidate by name warmly and professionally.
2. Immediately transition to the first interview question by referencing a specific piece of experience, skill, or education mentioned in their CV/Resume that is relevant to the {position} role. Make it clear you are asking based on their CV.
3. Throughout the interview, formulate questions by referring directly to the candidate's CV and the job description. Use question types like:\n- 'I noticed you worked with [Technology/Tool] at [Company]. Can you tell me about a specific project where you used it and your role in that project?'\n- 'Your experience at [Previous Company] seems relevant to this role. What were your main responsibilities and what results did you achieve?'\n- 'I see you have experience with [Specific Skill]. Can you share an example of how you applied this skill in a challenging situation?'\n- 'Your background in [Field/Area] is interesting. How has this experience prepared you for the challenges in this role?'\n- 'The job requires expertise in [Required Skill]. Based on your experience at [Company], how would you approach [Specific Task]?'
4. Listen actively to the candidate's responses and ask follow-up questions that connect their answers back to their resume details and the job requirements.
5. **If the candidate asks a direct factual question and the answer is available in the provided CV/Resume or the initial context you have (like their name or the job title), answer their question concisely and then smoothly transition back to your interview questions.** Do NOT say there will be time for questions later if you can answer it now based on the provided information.
6. Assess the candidate's alignment with the {position} role based on their CV and responses.

Interview Guidelines:
- Maintain a professional, friendly, and conversational tone throughout.
- Be polite and encouraging.
- Ensure your questions are clear and directly related to the CV content or the job description.
- Keep your own responses concise and natural.
- Focus on assessing both technical skills and soft skills relevant to the {position} role.
- Manage the flow of the conversation based on the candidate's responses, the points you need to cover from the CV/job description, and any questions they ask.

Interview Structure:
1. Start: Greet the candidate by name and immediately ask your first question based on their CV.
2. Core: Conduct the main interview, asking detailed, CV-based questions, listening to answers, asking follow-ups, and answering candidate's direct factual questions when possible based on provided information.
3. Closing: Thank the candidate, briefly summarize the topics discussed (referencing their experience), outline next steps, and explicitly offer them a dedicated time to ask any remaining questions.

End the interview by:
1. Thanking the candidate for their time.
2. Providing a brief summary of what was discussed.
3. Outlining next steps in the process.
4. Explicitly opening the floor for *any* questions they may have that weren't addressed earlier.
"""
        else:
            system_prompt_content = f"""You are a professional job interviewer conducting a real-time voice interview with a candidate for the {position} role. Your primary goal is to assess their qualifications, motivation, and fit for this role by asking questions.

Candidate Information:
- Name: {name}
- Position: {position}
- Position Description: {job_desc}

No resume was provided. Please:
1. Greet the candidate by name warmly and professionally.
2. Acknowledge that you do not have their resume on file: "I notice we don't have your resume on file."
3. Ask for a verbal overview of their experience and background relevant to the {position} role.
4. Take sufficient time to establish their background through their verbal responses.
5. **If the candidate asks a direct factual question and the answer is available in the initial context you have (like their name or the job title), answer their question concisely and then smoothly transition back to your interview questions.** Do NOT say there will be time for questions later if you can answer it now based on the provided information.
6. Assess the candidate's alignment with the {position} role based on their verbal responses and the job description.

Interview Guidelines:
- Maintain a professional, friendly, and conversational tone throughout.
- Be polite and encouraging.
- Ensure your questions are clear and relevant to the job description.
- Keep your own responses concise and natural.
- Focus on assessing both technical skills and soft skills relevant to the {position} role.
- Manage the flow of the conversation based on the candidate's responses and any questions they ask.

Interview Structure:
1. Start: Greet the candidate by name and acknowledge no resume is on file, then ask for their verbal overview.
2. Core: Conduct the main interview based on their verbal overview and the job description, asking follow-ups, and answering candidate's direct factual questions when possible based on provided information.
3. Closing: Thank the candidate, briefly summarize the topics discussed, outline next steps, and explicitly offer them a dedicated time to ask any remaining questions.

End the interview by:
1. Thanking the candidate for their time.
2. Providing a brief summary of what was discussed.
3. Outlining next steps in the process.
4. Explicitly opening the floor for *any* questions they may have that weren't addressed earlier.
"""

        # --- Initiate Vapi call with the dynamic assistant configuration ---
        logger.info("Initiating Vapi call with dynamic assistant configuration...")

        vapi_call_payload = {
            "assistant": { # Include the full assistant object
                "model": {
                    "provider": "anthropic", # Use the desired model provider
                    "model": "claude-3-opus-20240229", # Use the desired model
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt_content
                        }
                    ]
                },
                "voice": {
                    "provider": "azure", # Use the desired voice provider
                    "voiceId": "andrew" # Use the desired voice ID
                },
                "firstMessage": f"Hello {name}! I'm your AI interviewer for the {position} position. Are you ready to begin the interview?",
                "endCallFunctionEnabled": True,
                "serverMessages": [ # Explicitly list server messages to receive
                    "end-of-call-report",
                    "status-update",
                    "function-call"
                    # Add any other necessary server messages here
                ]
                 # Do NOT include assistantId here when providing the full assistant object
            },
            "customer": {
                "number": phone_number
            },
             "phoneNumber": { # Include Twilio details for outbound call
                "twilioPhoneNumber": TWILIO_PHONE_NUMBER,
                "twilioAccountSid": TWILIO_ACCOUNT_SID,
                "twilioAuthToken": TWILIO_AUTH_TOKEN
            },
            "metadata": { # Include metadata for your reference
                "interviewId": interview_id,
                "name": name,
                "position": position,
                "jobDescription": job_desc,
                "has_resume": has_resume
            },
        }

        headers = {
            "Authorization": f"Bearer {PRIVATE_KEY}", # Use PRIVATE_KEY for server-side API calls
            "Content-Type": "application/json"
        }

        logger.debug(f"Sending Vapi call initiation payload directly to {VAPI_BASE_URL}/call: {json.dumps(vapi_call_payload, indent=2)}")

        # Make the request directly to Vapi's /call API
        response = requests.post(
            f"{VAPI_BASE_URL}/call",
            json=vapi_call_payload,
            headers=headers,
            timeout=30
        )

        response.raise_for_status() # Raise an exception for bad status codes

        vapi_response_data = response.json()
        logger.debug(f"Response from Vapi /call API: {json.dumps(vapi_response_data, indent=2)}")

        # Extract the call SID from Vapi's response if available
        # Try the primary location first, then a fallback
        call_sid = vapi_response_data.get('phoneCall', {}).get('providerId')
        if not call_sid:
             # Fallback: check if it's directly under 'transport'
             call_sid = vapi_response_data.get('transport', {}).get('callSid')
             if call_sid:
                 logger.debug("Extracted Call SID from 'transport.callSid' fallback.")

        vapi_call_id = vapi_response_data.get('id') # Vapi's internal call ID

        # Store essential call data for potential later use (e.g., status updates, webhook correlation)
        if call_sid:
            call_data_store[call_sid] = {
                'vapi_call_id': vapi_call_id,
                'twilio_status': 'initiated', # Initial status
                'vapi_status': vapi_response_data.get('status', 'queued'), # Status from Vapi response
                'interview_details': interview_details, # Store full details for easy lookup
                'documents_verified': True, # Assuming processing succeeded prior
                # The vapi_websocket_url might be returned in the *initial* response for some call types,
                # or it might be something your webhook returns for assistant-request?
                # Let's rely on the webhook providing the config, and the /voice endpoint
                # retrieving the websocket URL from the call_data_store after the proxy
                # has potentially added it from the initial /call response.
            }
            logger.debug(f"Stored initial call data for SID: {call_sid}")
        else:
             logger.warning("Call SID not found in Vapi initiation response. Cannot store call data by SID.")

        # Render the HTML success page after successful Vapi call initiation request
        return render_template_string(
                        CALL_SUCCESS_PAGE,
            call_id=vapi_call_id or "N/A",  # Use Vapi's call ID if available
            status=vapi_response_data.get('status', 'initiated'),  # Use status from Vapi response
                        destination_number=phone_number
        ), 200 # Return 200 for success

    except requests.exceptions.RequestException as e:
        logger.error(f"Network or Vapi initiation error: {str(e)}")
        # Attempt to extract more specific error info if available
        try:
            error_response = e.response.json() if e.response else {}
            error_message = error_response.get('message', str(e))
            error_details = error_response.get('details', '')
            logger.error(f"Vapi Initiation Error Details: {error_details}")
        except: # Fallback for non-JSON responses
            error_message = str(e)
            error_details = e.response.text if e.response is not None else 'N/A'
            logger.error(f"Vapi Initiation Error Raw Response: {error_details}")

    return jsonify({
            "error": f"Failed to initiate Vapi call: {error_message}",
            "details": error_details
        }), e.response.status_code if e.response is not None else 500


@app.route("/call-status", methods=["POST"])
def call_status():
    """Handle call status updates with enhanced Vapi session logging"""
    try:
        logger.debug("="*50)
        logger.debug("CALL STATUS UPDATE RECEIVED")
        logger.debug("="*50)
        
        # Get basic call information
        call_sid = request.form.get('CallSid')
        call_status = request.form.get('CallStatus')
        call_duration = request.form.get('CallDuration')
        
        logger.debug(f"Call SID: {call_sid}")
        logger.debug(f"Call Status: {call_status}")
        logger.debug(f"Call Duration: {call_duration}")
        
        # Get Vapi session information if available
        if call_sid in call_data_store:
            call_data = call_data_store[call_sid]
            vapi_call_id = call_data.get('vapi_call_id')
            interview_details = call_data.get('interview_details', {})
            
            logger.debug("\n=== VAPI SESSION INFORMATION ===")
            logger.debug(f"Vapi Call ID: {vapi_call_id}")
            logger.debug(f"Interview ID: {interview_details.get('interview_id', 'N/A')}")
            logger.debug(f"Candidate Name: {interview_details.get('name', 'N/A')}")
            logger.debug(f"Job Title: {interview_details.get('job_title', 'N/A')}")
            logger.debug(f"Resume Provided: {'Yes' if interview_details.get('resume_content') else 'No'}")
            
            # Log document verification status
            logger.debug("\n=== DOCUMENT VERIFICATION STATUS ===")
            if call_data.get('documents_verified'):
                logger.debug("✓ Documents successfully received by Vapi")
                logger.debug("✓ Resume content verified")
                logger.debug("✓ System prompt verified")
            else:
                logger.debug("⚠ Documents not verified by Vapi")
            
            # Try to get current Vapi call status
            try:
                if vapi_call_id:
                    # Construct the payload for checking call status
                    payload = {
                        "endpoint": f"/call/{vapi_call_id}",
                        "method": "GET"
                    }
                    
                    # Send the request to Vapi
                    response = requests.post(
                        f"{request.url_root.rstrip('/')}/vapi-proxy",
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        vapi_status = response.json()
                        logger.debug("\n=== VAPI CALL STATUS ===")
                        logger.debug(f"Vapi Status: {vapi_status.get('status', 'N/A')}")
                        logger.debug(f"Vapi Duration: {vapi_status.get('duration', 'N/A')}")
                        logger.debug(f"Vapi Error: {vapi_status.get('error', 'None')}")
                        
                        # Update call data with Vapi status
                        call_data['vapi_status'] = vapi_status.get('status')
                        call_data['vapi_duration'] = vapi_status.get('duration')
                        call_data['vapi_error'] = vapi_status.get('error')
                    else:
                        logger.error(f"Failed to get Vapi status: {response.status_code}")
                        logger.error(f"Response: {response.text}")
            except Exception as e:
                logger.error(f"Error getting Vapi status: {str(e)}")
            
            # Update call data with Twilio status
            call_data['twilio_status'] = call_status
            if call_duration:
                call_data['twilio_duration'] = call_duration
            
            # Log the complete session state with clear status indicators
            logger.debug("\n=== COMPLETE SESSION STATE ===")
            logger.debug("Document Status:")
            logger.debug(f"  ✓ Documents Verified: {call_data.get('documents_verified', False)}")
            logger.debug("Vapi Status:")
            logger.debug(f"  ✓ Vapi Call Active: {call_data.get('vapi_status') == 'in-progress'}")
            logger.debug(f"  ✓ Vapi Duration: {call_data.get('vapi_duration', 'N/A')}")
            logger.debug("Twilio Status:")
            logger.debug(f"  ✓ Twilio Status: {call_data.get('twilio_status')}")
            logger.debug(f"  ✓ Twilio Duration: {call_data.get('twilio_duration', 'N/A')}")
            
            # Log full call data for debugging
            logger.debug("\nFull Call Data:")
            logger.debug(json.dumps(call_data, indent=2))
            
        else:
            logger.warning(f"No call data found for SID: {call_sid}")
        
       
        
        # Return a 204 No Content response to acknowledge receipt
        return '', 204
        
    except Exception as e:
        logger.error(f"Error in call status endpoint: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Return a 500 Internal Server Error if something goes wrong
        return '', 500

@app.route("/get-twilio-token", methods=["GET"])
def get_twilio_token():
    """Generate a Twilio Client token for browser-based calling"""
    try:
        # Create an Access Token with specific identity
        identity = f"user-{uuid.uuid4()}"
        access_token = AccessToken(
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN,
            TWILIO_APP_SID,
            identity=identity
        )
        
        # Create a Voice grant with minimal configuration
        voice_grant = VoiceGrant(
            outgoing_application_sid=TWILIO_APP_SID,
            incoming_allow=True
        )
        
        # Add the voice grant to the token
        access_token.add_grant(voice_grant)
        
        # Generate the token
        token = access_token.to_jwt();
        logger.debug(f"Generated token for identity {identity}: {token[:20]}...");
        
        return jsonify({
            "token": token,
            "identity": identity
        })
    except Exception as e:
        logger.error(f"Error generating token: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    logger.error(f"404 error: {request.url}")
    if request.path.startswith('/api/'):
        return jsonify({
            "error": "Not found",
            "message": "The requested resource was not found",
            "path": request.path
        }), 404
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>404 - Not Found</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
            <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg text-center">
                <h1 class="text-4xl font-bold mb-4">404 - Not Found</h1>
                <p class="text-gray-400 mb-6">The page you're looking for doesn't exist.</p>
                <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                    Go Home
                </a>
            </div>
        </body>
        </html>
    """), 404

@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "twilio": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
            "vapi": bool(SHARE_KEY and ASSISTANT_ID)
        }
    })

# Add a new endpoint to check call status
@app.route("/check-call-status/<call_id>", methods=["GET"])
def check_call_status(call_id):
    """Check the status of a Vapi call"""
    try:
        # Construct the payload for checking call status
        payload = {
            "endpoint": f"/call/{call_id}",
            "method": "GET"
        }
        
        # Send the request to Vapi
        response = requests.post(
            f"{request.url_root.rstrip('/')}/vapi-proxy",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code >= 400:
            return jsonify({
                "error": f"Failed to get call status: {response.status_code}",
                "details": response.text
            }), response.status_code
            
        return jsonify(response.json())
        
    except Exception as e:
        logger.error(f"Error checking call status: {str(e)}")
        return jsonify({
            "error": "Failed to check call status",
            "details": str(e)
        }), 500

@app.route("/call", methods=["GET"])
def call_page():
    """Serve the call page"""
    return render_template("call.html")

@app.route("/interview/<interview_id>", methods=["GET"])
def shared_interview(interview_id):
    """Handle shared interview links"""
    # Debug session state at start
    debug_session()
    
    interview_data = INTERVIEW_LINKS.get(interview_id)
    if not interview_data:
        return render_template_string("""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8" />
                <title>Interview Not Found</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
                <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg text-center">
                    <h1 class="text-3xl font-bold mb-4">Interview Not Found</h1>
                    <p class="text-gray-400 mb-6">This interview link is invalid or has expired.</p>
                    <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
                        Create New Interview
                    </a>
                </div>
            </body>
            </html>
        """), 404
    
    # Store the interview details in session
    interview_data['interview_id'] = interview_id  # Add interview ID to the data
    session['interview_details'] = interview_data
    session.modified = True
    
    # Debug session state after update
    debug_session()
    
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Interview Options</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script>
                // Enhanced localStorage management
                const InterviewStorage = {
                    STORAGE_KEY: 'interviewData',
                    
                    // Save interview data with validation
                    saveInterviewData: function(data) {
                        try {
                            // Validate required fields
                            if (!data.name || !data.job_title || !data.job) {
                                console.error('Missing required fields in interview data');
                                return false;
                            }
                            
                            // Add timestamp for data freshness
                            data.timestamp = new Date().toISOString();
                            
                            // Save to localStorage
                            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data));
                            
                            // Verify data was saved correctly
                            const saved = this.getInterviewData();
                            return saved && saved.timestamp === data.timestamp;
                        } catch (error) {
                            console.error('Error saving interview data:', error);
                            return false;
                        }
                    },
                    
                    // Get interview data with validation
                    getInterviewData: function() {
                        try {
                            const data = localStorage.getItem(this.STORAGE_KEY);
                            if (!data) return null;
                            
                            const parsed = JSON.parse(data);
                            
                            // Check if data is too old (e.g., 24 hours)
                            const dataAge = new Date() - new Date(parsed.timestamp);
                            if (dataAge > 24 * 60 * 60 * 1000) {
                                this.clearInterviewData();
                                return null;
                            }
                            
                            return parsed;
                        } catch (error) {
                            console.error('Error reading interview data:', error);
                            this.clearInterviewData();
                            return null;
                        }
                    },
                    
                    // Clear interview data
                    clearInterviewData: function() {
                        try {
                            localStorage.removeItem(this.STORAGE_KEY);
                            return true;
                        } catch (error) {
                            console.error('Error clearing interview data:', error);
                            return false;
                        }
                    },
                    
                    // Update session from localStorage
                    updateSession: async function() {
                        try {
                            const data = this.getInterviewData();
                            if (!data) return false;
                            
                            const response = await fetch('/update-session', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(data)
                            });
                            
                            if (!response.ok) throw new Error('Failed to update session');
                            
                            return true;
                        } catch (error) {
                            console.error('Error updating session:', error);
                            return false;
                        }
                    }
                };

                // Initialize interview data when page loads
                window.onload = function() {
                    const interviewData = {
                        name: "{{ name }}",
                        job_title: "{{ job_title }}",
                        job: "{{ job }}",
                        resume: "{{ interview_details.get('resume_content', '') }}",
                        interview_id: "{{ interview_id }}"
                    };
                    
                    // Save data and verify
                    if (InterviewStorage.saveInterviewData(interviewData)) {
                        console.log('Interview data saved successfully');
                    } else {
                        console.error('Failed to save interview data');
                    }
                    
                    // Check session and update if needed
                    fetch('/check-session')
                        .then(response => response.json())
                        .then(data => {
                            if (!data.hasInterviewDetails) {
                                InterviewStorage.updateSession()
                                    .then(success => {
                                        if (success) {
                                            console.log('Session updated from localStorage');
                                            // Optionally reload the page to show updated data
                                            // window.location.reload();
                                        } else {
                                            console.error('Failed to update session');
                                        }
                                    });
                            }
                        })
                        .catch(error => console.error('Error checking session:', error));
                };
            </script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-6">
            <div class="bg-gray-800 p-8 rounded-lg shadow-md w-full max-w-lg space-y-6">
                <div class="text-center mb-6">
                    <h1 class="text-3xl font-bold mb-2">Interview for {{ name }}</h1>
                    <p class="text-lg text-gray-400">Job Title: {{ job_title }}</p>
                    <p class="text-lg text-gray-400 mb-6 text-center">Position: {{ job }}</p>
                </div>

                <div class="space-y-4">
                    <a href="/interview/instant" class="block w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-4 px-6 rounded text-center text-lg">
                        Instant Interview (Browser)
                    </a>
                    <a href="/interview/call-number" class="block w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-4 px-6 rounded text-center text-lg">
                        Phone Interview
                    </a>
                </div>

                <div class="bg-gray-700 p-4 rounded-lg mt-6">
                    <h2 class="text-xl font-semibold mb-2">Interview Details</h2>
                    <ul class="space-y-2 text-gray-300">
                        <li><strong>Candidate:</strong> {{ name }}</li>
                        <li><strong>Job Title:</strong> {{ job_title }}</li>
                        <li><strong>Position:</strong> {{ job }}</li>
                        {% if interview_details.get('resume_content') %}
                        <li class="text-green-400">✓ Resume provided</li>
                        {% else %}
                        <li class="text-yellow-400">⚠ No resume provided</li>
                        {% endif %}
                    </ul>
                </div>
            </div>
        </body>
        </html>
    """, 
    name=interview_data['name'],
    job_title=interview_data['job_title'],
    job=interview_data['job'],
    interview_details=interview_data,
    interview_id=interview_id
    )

# Update the system_prompt variable
system_prompt ='''You are a professional job interviewer conducting a real-time voice interview with a candidate. Your goal is to assess their qualifications, motivation, and fit for the role.

IMPORTANT - RESUME STATUS CHECK:
{% if metadata.has_resume and metadata.resume %}
✓ Resume received and loaded successfully
{% else %}
⚠ No resume provided
{% endif %}

Candidate Information:
- Name: {{metadata.name}}
- Position: {{metadata.position}}
{% if metadata.jobDescription %}
- Position Description: {{metadata.jobDescription}}
{% endif %}

{% if metadata.has_resume and metadata.resume %}
CANDIDATE'S CV/RESUME:
==================
{{metadata.resume}}
==================

Interview Instructions:
1. START by confirming: "I have your resume in front of me and can see your experience in [mention 1-2 specific points]"
2. Use resume details to guide relevant questions
3. Reference specific experiences/projects from their CV
4. Assess alignment with the {{metadata.position}} role
{% else %}
No resume was provided. Please:
1. Acknowledge this: "I notice we don't have your resume on file"
2. Ask for a verbal overview of their experience
3. Take more time to establish their background
{% endif %}

Interview Guidelines:
- Be professional and polite
- Keep responses concise and conversational
- Ask follow-up questions when needed
- Focus on both technical skills and soft skills
- End the interview professionally with next steps

Voice and Tone:
- Use a professional but friendly tone
- Speak clearly and at a moderate pace
- Maintain a natural conversation flow
- Show genuine interest in the candidate's responses

Interview Structure:
1. Introduction and rapport building
2. Experience and skills assessment
3. Technical knowledge evaluation
4. Soft skills and cultural fit assessment
5. Candidate questions and closing

End the interview by:
1. Thanking the candidate for their time
2. Providing a brief summary of what was discussed
3. Outlining next steps in the process
4. Offering to answer any questions they may have 
'''

@app.route('/update-session', methods=['POST'])
def update_session():
    """Update session with interview details from localStorage"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        # Update session with localStorage data
        session['interview_details'] = {
            'name': data.get('name', ''),
            'job_title': data.get('job_title', ''),
            'job': data.get('job', ''),
            'resume_content': data.get('resume', ''),
            'interview_id': data.get('interview_id', '')
        }
        session.modified = True
        
        logger.debug("="*50)
        logger.debug("SESSION UPDATED FROM LOCALSTORAGE")
        logger.debug("="*50)
        logger.debug(f"Updated interview details: {session['interview_details']}")
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/check-session')
def check_session():
    """Check if session has interview details"""
    try:
        # Debug session state
        debug_session()
        
        has_interview_details = bool(session.get('interview_details'))
        return jsonify({
            'hasInterviewDetails': has_interview_details,
            'sessionData': dict(session) if has_interview_details else None
        })
    except Exception as e:
        logger.error(f"Error checking session: {str(e)}")
        return jsonify({
            'error': str(e),
            'hasInterviewDetails': False
        }), 500

@app.route("/validate-resume", methods=["POST"])
def validate_resume():
    """Validate resume content"""
    try:
        interview_details = session.get('interview_details', {})
        resume_content = interview_details.get('resume_content', '')
        
        validation_result = {
            "has_resume": bool(resume_content),
            "resume_length": len(resume_content) if resume_content else 0,
            "resume_preview": resume_content[:200] if resume_content else None,
            "validation_status": "valid" if resume_content else "missing",
            "interview_id": interview_details.get('interview_id'),
        }
        
        logger.info("="*50)
        logger.info("RESUME VALIDATION RESULTS")
        logger.info("="*50)
        logger.info(json.dumps(validation_result, indent=2))
        
        return jsonify(validation_result)
        
    except Exception as e:
        logger.error(f"Resume validation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Now define INTERVIEW_PAGE after SHARE_KEY and ASSISTANT_ID are defined
INTERVIEW_PAGE = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>Interview: {{ name }}</title>
    <script src=\"https://cdn.tailwindcss.com\"></script>
    <style>
        .interview-container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        .status-indicator {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }}
        .status-active {{
            background-color: #10B981;
            box-shadow: 0 0 8px #10B981;
        }}
        .status-inactive {{
            background-color: #6B7280;
        }}
        .visualizer-container {{
            background: #1F2937;
            border-radius: 0.5rem;
                padding: 1rem;
            margin-top: 1rem;
        }}
    </style>
</head>
<body class=\"bg-gray-900 text-white\">
    <div class=\"interview-container\">
        <div class=\"mb-8\">
            <h1 class=\"text-3xl font-bold mb-2\">Interview for {{ name }}</h1>
            <p class=\"text-lg text-gray-400 mb-2\">Job Title: {{ job_title }}</p>
            <p class=\"text-lg text-gray-400 mb-4\">Position: {{ job }}</p>
            <div class=\"flex items-center mb-4\">
                <span class=\"status-indicator status-active\" id=\"connectionStatus\"></span>
                <span class=\"text-gray-300\" id=\"statusText\">Connecting to interview...</span>
        </div>
        </div>
        <div class=\"grid grid-cols-1 lg:grid-cols-2 gap-6\">
            <!-- Interview Widget -->
            <div class=\"bg-gray-800 rounded-lg p-6\">
                <h2 class=\"text-xl font-semibold mb-4\">Interview Session</h2>
                <div id=\"vapi-widget\"></div>
    </div>
            <!-- Visualizer and Status -->
            <div class=\"space-y-6\">
                <div class=\"bg-gray-800 rounded-lg p-6\">
                    <h2 class=\"text-xl font-semibold mb-4\">Interview Status</h2>
                    <div class=\"space-y-4\">
                        <div>
                            <h3 class=\"text-gray-400 mb-2\">Connection Status</h3>
                            <div class=\"flex items-center\">
                                <span class=\"status-indicator status-active\" id=\"audioStatus\"></span>
                                <span class=\"text-gray-300\" id=\"audioStatusText\">Audio Active</span>
                            </div>
                        </div>
                        <div>
                            <h3 class=\"text-gray-400 mb-2\">Interview Progress</h3>
                            <div class=\"w-full bg-gray-700 rounded-full h-2\">
                                <div class=\"bg-blue-600 h-2 rounded-full\" style=\"width: 0%\" id=\"progressBar\"></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class=\"visualizer-container\">
                    <h2 class=\"text-xl font-semibold mb-4\">Audio Visualizer</h2>
                    <canvas id=\"audioVisualizer\" class=\"w-full h-32\"></canvas>
                </div>
            </div>
        </div>
    </div>
    <!-- Vapi Widget Script -->
    <script>
        (function (d, t) {{
            var g = d.createElement(t), s = d.getElementsByTagName(t)[0];
            g.src = "https://cdn.jsdelivr.net/gh/VapiAI/html-script-tag@latest/dist/assets/index.js";
            g.defer = true;
            g.async = true;
            s.parentNode.insertBefore(g, s);
            g.onload = function () {{
                // Render the widget inside #vapi-widget
                window.vapiSDK.run({{
                    apiKey: "{SHARE_KEY}",
                    assistant: "{ASSISTANT_ID}",
                    container: document.getElementById('vapi-widget'), // Ensure widget renders in the correct div
                    metadata: {{
                        candidate_name: "{{ name }}",
                        job_title: "{{ job_title }}",
                        job_description: "{{ job }}",
                        interviewId: "{{ interview_id }}",
                        resume_text: "{{ resume_content }}",
                        has_resume: {{ has_resume | tojson }}
                    }},
                    onStatusChange: function(status) {{
                        document.getElementById('statusText').textContent = status;
                        if (status === 'connected') {{
                            document.getElementById('connectionStatus').classList.add('status-active');
                        }} else {{
                            document.getElementById('connectionStatus').classList.remove('status-active');
                        }}
                    }},
                    onAudioActivity: function(isActive) {{
                        document.getElementById('audioStatusText').textContent = isActive ? 'Audio Active' : 'Audio Inactive';
                        document.getElementById('audioStatus').classList.toggle('status-active', isActive);
                    }},
                    onReady: function() {{
                        // Only initialize the visualizer when the widget is ready and audio stream is available
                        if (window.vapiSDK && window.vapiSDK.getAudioStream) {{
                            const stream = window.vapiSDK.getAudioStream();
                            if (stream) {{
                                initVisualizer(stream);
                            }}
                        }}
                    }}
                }}); // End of window.vapiSDK.run()
            }};
        }})(document, "script");
        // Audio Visualizer logic
        function initVisualizer(stream) {{
            const canvas = document.getElementById('audioVisualizer');
            const ctx = canvas.getContext('2d');
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            const source = audioContext.createMediaStreamSource(stream);
            source.connect(analyser);
            function draw() {{
                requestAnimationFrame(draw);
                analyser.getByteFrequencyData(dataArray);
                ctx.fillStyle = '#1F2937';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                const barWidth = (canvas.width / dataArray.length) * 2.5;
                let barHeight;
                let x = 0;
                for(let i = 0; i < dataArray.length; i++) {{
                    barHeight = dataArray[i] / 2;
                    const gradient = ctx.createLinearGradient(0, canvas.height, 0, 0);
                    gradient.addColorStop(0, '#3B82F6');
                    gradient.addColorStop(1, '#60A5FA');
                    ctx.fillStyle = gradient;
                    ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                    x += barWidth + 1;
                }}
            }}
            draw();
        }}
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
    

