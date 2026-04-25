"""
ai_brain.py
-----------
Manages AI conversation logic using OpenAI GPT API.
Falls back to a built-in rule-based engine if OpenAI is not configured.
Maintains short-term conversation memory (rolling window).
"""

import logging
import datetime
from collections import deque

logger = logging.getLogger(__name__)

# ─── Attempt OpenAI Import ───────────────────────────────────────────────────
try:
    from openai import OpenAI, AuthenticationError, RateLimitError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai package not installed. Using fallback brain.")


class AIBrain:
    """
    Core intelligence module for Jarvis.
    - Uses OpenAI GPT for natural language understanding if API key is set.
    - Falls back to rule-based responses for common engineering/general queries.
    - Maintains a rolling conversation memory window.
    """

    # System personality prompt — defines Jarvis's character
    SYSTEM_PROMPT = (
        "You are Jarvis, a highly intelligent, sophisticated AI assistant — "
        "inspired by the AI from Iron Man. You speak with calm confidence, precision, "
        "and a hint of dry wit. You address the user respectfully. "
        "You are knowledgeable in electronics, electrical engineering, physics, math, "
        "and general knowledge. Keep responses concise (2–4 sentences unless asked for more). "
        "Never break character."
    )

    def __init__(self, config: dict):
        self.config = config
        self.use_openai = config.get("use_openai", False) and OPENAI_AVAILABLE
        self.model = config.get("openai_model", "gpt-3.5-turbo")
        self.use_ollama = config.get("use_ollama", False)
        self.ollama_model = config.get("ollama_model", "llama3")
        self.max_memory = config.get("max_memory_turns", 10)

        # Rolling conversation history (user + assistant pairs)
        self.memory: deque = deque(maxlen=self.max_memory * 2)

        self._client = None
        if self.use_openai:
            api_key = config.get("openai_api_key", "")
            if api_key and api_key != "YOUR_OPENAI_API_KEY_HERE":
                self._client = OpenAI(api_key=api_key)
                logger.info("OpenAI brain initialized (SDK v2).")
            else:
                logger.warning("No valid OpenAI key. Switching to fallback brain.")
                self.use_openai = False

    def ask(self, user_input: str) -> str:
        """
        Process user input and return Jarvis's response.

        Args:
            user_input (str): The text from the user.

        Returns:
            str: Jarvis's generated response.
        """
        # Save user message to memory
        self.memory.append({"role": "user", "content": user_input})

        response = None
        
        if self.use_openai:
            response = self._ask_openai()
            
        if not response and self.use_ollama:
            response = self._ask_ollama()
            
        if not response:
            response = self._ask_fallback(user_input)

        # Save assistant reply to memory
        self.memory.append({"role": "assistant", "content": response})
        return response

    def _ask_openai(self) -> str:
        """Send conversation history to OpenAI and get a reply (SDK v2)."""
        try:
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
            messages.extend(list(self.memory))

            chat = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.75,
                max_tokens=300,
            )
            reply = chat.choices[0].message.content.strip()
            logger.info(f"[OpenAI Response] {reply}")
            return reply
        except AuthenticationError:
            logger.error("OpenAI Authentication failed. Check your API key. Falling through.")
            return None
        except RateLimitError:
            logger.error("OpenAI rate limit exceeded. Falling through.")
            return None
        except Exception as e:
            logger.error(f"OpenAI error: {e}. Falling through.")
            return None

    def _ask_ollama(self) -> str | None:
        """Send conversation history to local Ollama instance."""
        import urllib.request
        import urllib.error
        import json
        
        try:
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
            messages.extend(list(self.memory))
            
            payload = {
                "model": self.ollama_model,
                "messages": messages,
                "stream": False
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            logger.info(f"Querying Ollama with model {self.ollama_model}...")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    result = json.loads(response.read().decode('utf-8'))
                    reply = result.get("message", {}).get("content", "").strip()
                    logger.info(f"[Ollama Response] {reply}")
                    return reply
                else:
                    logger.warning(f"Ollama returned status code {response.status}.")
                    return None
        except Exception as e:
            logger.warning(f"Ollama unavailable or error: {e}")
            return None

    def _ask_fallback(self, text: str) -> str:
        """
        Rule-based fallback brain when OpenAI is unavailable.
        Handles engineering, math, and general queries locally.
        """
        text = text.lower().strip()
        name = self.config.get("user_name", "Sir")

        # ─── Engineering / Electrical ────────────────────────────────────
        if any(kw in text for kw in ["ohm's law", "ohm law", "voltage current resistance"]):
            return (
                "Ohm's Law states: V = I × R, where V is voltage in volts, "
                "I is current in amperes, and R is resistance in ohms. "
                "It forms the fundamental relationship in electrical circuits."
            )
        if "power formula" in text or ("power" in text and "watt" in text):
            return (
                "Electrical power is calculated as P = V × I, "
                "or equivalently P = I² × R, or P = V² / R. "
                "Power is measured in watts."
            )
        if "kirchhoff" in text:
            return (
                "Kirchhoff's Current Law states that the sum of currents entering a node equals "
                "the sum leaving it. Kirchhoff's Voltage Law states that the sum of all voltages "
                "around a closed loop equals zero."
            )
        if "capacitor" in text and ("formula" in text or "charge" in text):
            return "A capacitor stores charge: Q = C × V, where Q is charge in coulombs, C is capacitance in farads, and V is voltage."
        if "inductor" in text or "inductance" in text:
            return "Inductance relates voltage to the rate of current change: V = L × (dI/dt). Inductors oppose changes in current and store energy in magnetic fields."
        if "frequency" in text and ("formula" in text or "calculate" in text):
            return "Frequency f = 1/T, where T is the period in seconds. In AC circuits, f is measured in Hertz (Hz)."
        if "resistor in series" in text or "series resistance" in text:
            return "For resistors in series: R_total = R1 + R2 + R3 + ... Each resistor adds to total resistance."
        if "resistor in parallel" in text or "parallel resistance" in text:
            return "For resistors in parallel: 1/R_total = 1/R1 + 1/R2 + ... This always results in a total less than the smallest individual resistor."

        # ─── Math ─────────────────────────────────────────────────────────
        if any(kw in text for kw in ["calculate", "compute", "solve", "what is"]):
            result = self._try_math(text)
            if result:
                return result

        if "pythagorean" in text:
            return "The Pythagorean Theorem: a² + b² = c², where c is the hypotenuse of a right triangle."
        if "quadratic" in text:
            return "The quadratic formula: x = (-b ± √(b² - 4ac)) / 2a. It solves any equation of the form ax² + bx + c = 0."
        if "derivative" in text or "differentiation" in text:
            return "Differentiation finds the rate of change. For f(x) = xⁿ, the derivative is f'(x) = n·xⁿ⁻¹. This is the power rule."
        if "integration" in text or "integral" in text:
            return "Integration is the reverse of differentiation. ∫xⁿ dx = xⁿ⁺¹/(n+1) + C, which is the power rule for integration."

        # ─── General conversation ─────────────────────────────────────────
        if "how are you" in text:
            return f"All systems are operating at peak efficiency, {name}. Ready to assist."
        if "your name" in text or "who are you" in text:
            return f"I am Jarvis — Just A Rather Very Intelligent System. At your service, {name}."
        if "thank" in text:
            return f"It's what I'm here for, {name}. Always."
        if "joke" in text:
            return "Why do engineers prefer dark mode? Because light attracts bugs, {name}.".format(name=name)
        if "hello" in text or "hi" in text or "hey" in text:
            return f"Good to hear from you, {name}. How may I assist you today?"
        if "help" in text:
            return (
                f"Of course, {name}. I can open applications, search the web, answer engineering questions, "
                "tell you the time, play music, or just have a conversation. What do you need?"
            )

        # ─── Wikipedia Fallback ──────────────────────────────────────────
        for wiki_kw in ["who is", "what is", "where is", "tell me about"]:
            if wiki_kw in text:
                query = text.split(wiki_kw, 1)[-1].strip()
                if query:
                    try:
                        import wikipedia
                        logger.info(f"Searching Wikipedia for: {query}")
                        wiki_summary = wikipedia.summary(query, sentences=2, auto_suggest=True)
                        return f"According to my records, {wiki_summary}"
                    except ImportError:
                        logger.warning("Wikipedia module not installed.")
                    except wikipedia.exceptions.DisambiguationError as e:
                        try:
                            wiki_summary = wikipedia.summary(e.options[0], sentences=2)
                            return f"Here is what I found: {wiki_summary}"
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug(f"Wikipedia search failed: {e}")

        # ─── Default ──────────────────────────────────────────────────────
        return (
            f"That's an interesting query, {name}. Unfortunately, my offline reasoning module "
            "has limited scope. For deeper insights, I'd recommend enabling my OpenAI integration."
        )

    def _try_math(self, text: str) -> str | None:
        """
        Attempt to evaluate simple arithmetic from natural language.
        Extracts mathematical expressions using eval (safely restricted).
        """
        import re
        # Extract numeric expressions like "2 + 2", "45 * 3", "100 / 4"
        pattern = r"[-+]?\d+(?:\.\d+)?(?:\s*[\+\-\*\/\%\^]\s*[-+]?\d+(?:\.\d+)?)*"
        match = re.search(pattern, text)
        if match:
            expr = match.group().replace("^", "**")
            try:
                # Safe eval: only allow numbers and basic operators
                allowed = set("0123456789+-*/()%. \n")
                if all(c in allowed for c in expr):
                    result = eval(expr)
                    return f"The result of {match.group()} is {result}, {self.config.get('user_name', 'Sir')}."
            except Exception:
                pass
        return None

    def clear_memory(self):
        """Clear the conversation memory buffer."""
        self.memory.clear()
        logger.info("Conversation memory cleared.")
