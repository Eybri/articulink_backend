import google.generativeai as genai
import os
from typing import List, Dict, Optional

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel(model_name="models/gemini-2.5-flash")

SYSTEM_PROMPT = """
You are the professional Articulink Chat Support assistant.

Articulink is a specialized communication tool partnered with the Cleft Foundation. It helps users with speech differences—specifically lisp and hypernasality—be understood clearly in real-time.

Core Articulink Features & Tutorial:
1. RECORD (Home Screen): Tap the microphone to record. Your speech is converted to clear text and you can tap "Speak" to hear a clarified version.
2. AUDIO CLIPS: Save your common phrases for easy playback later.
3. HISTORY: View and manage your previous recordings and saved clips.
4. MAPS: Find the nearest speech therapy clinics and PWD-friendly centers on the Map tab.

Your instructions:
1. ROLE: Professional Product Expert & Communication Supporter.
2. LANGUAGE: Detect the user's language and respond in the SAME language (e.g., Tagalog, English, or Taglish).
3. SCOPE: Focus on Articulink features, the Cleft Foundation partnership, and communication tips.
4. BREVITY: Be concise (1-2 sentences). Use 3-4 sentences ONLY when providing a tutorial.
5. MEDICAL: You are not a doctor. If asked about surgery or healing clefts, say: "I cannot provide medical advice. Articulink focuses on assisting your current communication through AI tools."
6. COMPLETION: ALWAYS end with a period. NEVER stop mid-sentence.

Stay on-topic. Be helpful.
"""


def build_prompt(messages: List[Dict[str, str]], user_summary: Optional[str] = None) -> str:
    prompt = f"System Instruction: {SYSTEM_PROMPT.strip()}\n\n"
    if user_summary:
        prompt += f"Background: {user_summary}\n\n"
    for msg in messages[-6:]:
        role = "User" if msg["role"] == "user" else "Support"
        prompt += f"{role}: {msg['content']}\n"
    prompt += "Support (in the user's language):"
    return prompt


async def generate_gemini_reply(messages: List[Dict[str, str]], user_summary: Optional[str] = None) -> str:
    try:
        prompt = build_prompt(messages, user_summary)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2, "max_output_tokens": 350},
            safety_settings=safety_settings
        )
        if not response or not response.candidates:
            return "Pasensya na, hindi ko ma-process ang request na iyon. Paano kita matutulungan sa Articulink?"
        candidate = response.candidates[0]
        if candidate.finish_reason.name == "SAFETY":
            return "I'm sorry, I cannot provide medical diagnosis. Articulink is here to help with your communication!"
        text = response.text.strip()
        if text and text[-1] not in ".!?":
            last_punc = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
            text = text[:last_punc + 1] if last_punc > 0 else text + "."
        return text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "I'm having a bit of trouble connecting. Pakisubukang muli mamaya!"


async def generate_speech_analysis(records: List[Dict]) -> str:
    """
    Generates a descriptive analysis of the user's speech performance based on history.
    """
    try:
        # Prepare the context from records
        history_text = ""
        for i, rec in enumerate(records[:15]): # Analyze last 15 records
            transcript = rec.get("transcript", "")
            corrected = rec.get("corrected_transcript", "")
            accuracy = rec.get("confidence_score") or 0.95
            history_text += f"{i+1}. Raw: '{transcript}' -> Clarified: '{corrected}' (Accuracy: {accuracy*100:.1f}%)\n"
        
        print(f"DEBUG: Analysis History Text:\n{history_text}")

        analysis_prompt = f"""
        You are a Professional Speech Language Pathologist and Articulink Performance Analyst.
        
        Analyze the following speech history of a user with speech articulation differences (e.g., hypernasality or lisp):
        
        {history_text}
        
        Provide a DESCRIPTIVE PERFORMANCE REPORT including:
        1. OVERALL TREND: How is the user's clarity progressing?
        2. SPEECH PATTERNS: What specific phonetic or articulation areas seem to be common challenges based on the raw vs clarified text?
        3. CLINICAL TIPS: 1-2 practical, encouraging tips for improving their specific patterns.
        4. WEEKLY MOTIVATION: A short encouraging sentence.
        
        Guidelines:
        - Be professional, empathetic, and encouraging.
        - Use simple language.
        - Respond in the user's primary language detected from the transcripts (English or Tagalog/Taglish).
        - Keep the total report under 150 words.
        - DO NOT provide medical diagnosis.
        """

        response = model.generate_content(
            analysis_prompt,
            generation_config={"temperature": 0.3, "max_output_tokens": 500}
        )
        
        if not response or not hasattr(response, 'text') or not response.text:
            msg = "Unable to generate analysis at this time. Keep recording more to get a better report!"
            print(f"DEBUG: AI failed to generate text. Showing fallback: {msg}")
            return msg
            
        report_text = response.text.strip()
        print(f"DEBUG: Generated Analysis Report:\n{report_text}")
        return report_text
    except Exception as e:
        print(f"Speech Analysis Error: {e}")
        return "Insight generation encountered an error. Please try again after a few more recordings."
