"""
ai_brain.py
-----------
Manages AI conversation logic using the Groq API.
Falls back to a built-in rule-based engine if Groq is not configured.
Maintains short-term conversation memory (rolling window).
Includes ChromaDB RAG for long-term memory and context retrieval.
"""

import ast
import logging
import datetime
import operator
import re
from collections import deque
import requests
from pathlib import Path

logger = logging.getLogger(__name__)


class _RagDisabled(Exception):
    """Internal marker: RAG deliberately turned off for this instance."""


class AIBrain:
    """
    Core intelligence module for Nova.
    - Uses Groq-compatible chat completions for natural language understanding if API key is set.
    - Falls back to rule-based responses for common engineering/general queries.
    - Maintains a rolling conversation memory window.
    """

    # System personality prompt — defines Nova's character
    SYSTEM_PROMPT = (
        "You are Nova, a highly intelligent, sophisticated AI assistant — "
        "inspired by the AI from Iron Man. You speak with calm confidence, precision, "
        "and a hint of dry wit. You address the user respectfully. "
        "You are knowledgeable in electronics, electrical engineering, physics, math, "
        "and general knowledge. Keep responses concise (2–4 sentences unless asked for more). "
        "Never break character."
    )

    DEFAULT_GROQ_MODELS = (
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "llama3-70b-8192",
    )

    def __init__(self, config: dict, enable_rag: bool = True):
        """
        Args:
            config: Nova configuration dict.
            enable_rag: Set False for throw-away helper instances that should not
                load the embedding model or touch the persistent RAG store.
        """
        self.config = config
        self.use_groq = config.get("use_groq", config.get("use_openai", False))
        self.model_candidates = self._build_groq_model_candidates(config)
        self.model = self.model_candidates[0]
        self.api_key = str(config.get("groq_api_key", config.get("openai_api_key", "")) or "").strip()
        self._chat_url = "https://api.groq.com/openai/v1/chat/completions"
        self.use_ollama = config.get("use_ollama", False)
        self.ollama_model = config.get("ollama_model", "llama3")
        self.ollama_timeout = float(config.get("ollama_timeout", 60))  # local models can be slow to load
        try:
            # maxlen=0 would silently drop the user's message and make every LLM call fail.
            self.max_memory = max(1, int(config.get("max_memory_turns", 10)))
        except (TypeError, ValueError):
            self.max_memory = 10

        # Rolling conversation history (user + assistant pairs)
        self.memory: deque = deque(maxlen=self.max_memory * 2)

        # Initialize ChromaDB for RAG memory
        self.rag_enabled = False
        try:
            if not enable_rag:
                raise _RagDisabled()
            import chromadb
            from sentence_transformers import SentenceTransformer
            
            # Use persistent storage in .rag_memory directory
            self.rag_db_path = Path.home() / ".nova_rag_memory"
            self.rag_db_path.mkdir(parents=True, exist_ok=True)
            
            self.chroma_client = chromadb.PersistentClient(path=str(self.rag_db_path))
            self.rag_collection = self.chroma_client.get_or_create_collection(
                name="nova_exchanges",
                metadata={"hnsw:space": "cosine"}
            )
            
            # Initialize sentence transformer for embeddings
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            self.rag_enabled = True
            logger.info("ChromaDB RAG memory initialized successfully.")
        except _RagDisabled:
            pass
        except ImportError:
            logger.warning("ChromaDB or sentence-transformers not installed. RAG memory disabled.")
            self.rag_enabled = False
        except Exception as e:
            logger.warning(f"Failed to initialize ChromaDB RAG: {e}. RAG memory disabled.")
            self.rag_enabled = False

        if self.use_groq:
            if self.api_key and self.api_key not in {"YOUR_GROQ_API_KEY_HERE", "YOUR_OPENAI_API_KEY_HERE"}:
                logger.info("Groq brain initialized.")
            else:
                logger.warning("No valid Groq key. Switching to fallback brain.")
                self.use_groq = False

    def _build_groq_model_candidates(self, config: dict) -> list[str]:
        preferred_model = config.get("groq_model", config.get("openai_model", "llama-3.1-8b-instant"))
        configured_candidates = config.get("groq_model_candidates", [])

        ordered_models = [preferred_model, *configured_candidates, *self.DEFAULT_GROQ_MODELS]
        seen: set[str] = set()
        unique_models: list[str] = []
        for model in ordered_models:
            if model and model not in seen:
                unique_models.append(model)
                seen.add(model)
        return unique_models

    def ask(self, user_input: str) -> str:
        """
        Process user input and return Nova's response.
        Retrieves similar past exchanges from RAG memory before LLM call.

        Args:
            user_input (str): The text from the user.

        Returns:
            str: Nova's generated response.
        """
        # Save user message to memory
        self.memory.append({"role": "user", "content": user_input})

        # Retrieve similar past exchanges from RAG memory for context
        rag_context = self._retrieve_rag_context(user_input)

        response = None
        from_llm = False

        if self.use_groq:
            response = self._ask_groq(rag_context)

        if not response and self.use_ollama:
            response = self._ask_ollama(rag_context)

        if response:
            from_llm = True
        else:
            response = self._ask_fallback(user_input)

        # Save assistant reply to memory
        self.memory.append({"role": "assistant", "content": response})

        # Long-term RAG memory only keeps real LLM answers. Canned fallback replies
        # ("my offline reasoning module has limited scope...") would otherwise be
        # retrieved later as if they were useful past context.
        if from_llm:
            self._store_rag_exchange(user_input, response)

        return response

    def complete(self, prompt: str) -> str | None:
        """
        One-shot LLM completion that leaves conversation and RAG memory untouched.

        Used by plugins (e.g. web-search summaries). Returns None when no LLM
        backend is available or reachable, so callers can degrade gracefully
        instead of getting the rule-based chat fallback's canned reply.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        reply = None
        if self.use_groq:
            reply = self._ask_groq(messages=messages)
        if not reply and self.use_ollama:
            reply = self._ask_ollama(messages=messages)
        return reply or None

    def _build_messages(self, rag_context: str = "") -> list[dict]:
        """System prompt (+ RAG context) followed by the rolling conversation."""
        system_prompt = self.SYSTEM_PROMPT
        if rag_context:
            system_prompt = f"{self.SYSTEM_PROMPT}\n\n[Related Past Context]\n{rag_context}"
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(list(self.memory))
        return messages

    def _ask_groq(self, rag_context: str = "", messages: list[dict] | None = None) -> str | None:
        """Send conversation history (or explicit `messages`) to Groq and get a reply."""
        if messages is None:
            messages = self._build_messages(rag_context)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for model in self.model_candidates:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.75,
                    "max_tokens": 300,
                }
                response = requests.post(self._chat_url, json=payload, headers=headers, timeout=20)

                if response.status_code == 401:
                    logger.error("Groq authentication failed. Check your API key. Falling through.")
                    return None

                if response.status_code == 429:
                    logger.error("Groq rate limit exceeded. Falling through.")
                    return None

                if response.status_code == 400:
                    error_data = self._extract_groq_error(response)
                    if self._should_try_next_groq_model(error_data):
                        logger.warning(
                            f"Groq model '{model}' is unavailable. Trying next supported model."
                        )
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                data = response.json()
                reply = (data["choices"][0]["message"]["content"] or "").strip()
                if not reply:
                    continue
                logger.info(f"[Groq Response:{model}] {reply}")
                self.model = model
                return reply

            except (requests.ConnectionError, requests.Timeout) as e:
                # Offline / unreachable: trying more models would only multiply the wait.
                logger.error(f"Groq unreachable: {e}. Falling through.")
                return None
            except requests.RequestException as e:
                logger.error(f"Groq request failed for model '{model}': {e}. Falling through.")
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.error(f"Groq response parsing failed for model '{model}': {e}. Falling through.")
                return None
            except Exception as e:
                logger.error(f"Groq error for model '{model}': {e}. Falling through.")
                return None

        logger.error("All Groq model candidates failed. Falling through.")
        return None

    def _extract_groq_error(self, response: requests.Response) -> dict:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get("error", payload)
        except ValueError:
            pass
        return {}

    def _should_try_next_groq_model(self, error_data: dict) -> bool:
        error_code = str(error_data.get("code", "")).lower()
        message = str(error_data.get("message", "")).lower()
        return (
            error_code == "model_decommissioned"
            or "decommissioned" in message
            or "no longer supported" in message
            or "model" in message and "not found" in message
        )

    def _ask_ollama(self, rag_context: str = "", messages: list[dict] | None = None) -> str | None:
        """Send conversation history (or explicit `messages`) to a local Ollama instance."""
        import urllib.request
        import urllib.error
        import json

        try:
            if messages is None:
                messages = self._build_messages(rag_context)

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
            with urllib.request.urlopen(req, timeout=self.ollama_timeout) as response:
                if response.status == 200:
                    result = json.loads(response.read().decode('utf-8'))
                    reply = (result.get("message", {}).get("content", "") or "").strip()
                    logger.info(f"[Ollama Response] {reply}")
                    return reply or None
                else:
                    logger.warning(f"Ollama returned status code {response.status}.")
                    return None
        except Exception as e:
            logger.warning(f"Ollama unavailable or error: {e}")
            return None

    def _ask_fallback(self, text: str) -> str:
        """
        Rule-based fallback brain when Groq is unavailable.
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
            return f"I am Nova, your personal AI assistant. At your service, {name}."
        if re.search(r"\bthank(s| you)?\b", text):
            return f"It's what I'm here for, {name}. Always."
        if "joke" in text:
            return "Why do engineers prefer dark mode? Because light attracts bugs, {name}.".format(name=name)
        # Whole words only: a substring test makes "hi" match "this", "which", "philosophy"...
        if re.search(r"\b(hello|hi|hey)\b", text):
            return f"Good to hear from you, {name}. How may I assist you today?"
        if re.search(r"\bhelp\b", text):
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
            "has limited scope. For deeper insights, enable Groq in config.json by setting use_groq to true and providing a groq_api_key."
        )

    # ─── Safe arithmetic ──────────────────────────────────────────────────────

    _BIN_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _MAX_EXPONENT = 100
    _MAX_OPERAND = 1e12

    @classmethod
    def _safe_eval(cls, node):
        """
        Evaluate an arithmetic AST with a strict whitelist.

        Only numbers, + - * / // % ** and unary +/- are allowed, and exponents
        are capped. (A character whitelist plus eval() is not enough: "9**9**9**9"
        passes it and freezes the assistant.)
        """
        if isinstance(node, ast.Expression):
            return cls._safe_eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if abs(node.value) > cls._MAX_OPERAND:
                raise ValueError("operand too large")
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = cls._safe_eval(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in cls._BIN_OPS:
            left = cls._safe_eval(node.left)
            right = cls._safe_eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > cls._MAX_EXPONENT:
                raise ValueError("exponent too large")
            result = cls._BIN_OPS[type(node.op)](left, right)
            if isinstance(result, complex):
                raise ValueError("complex result")
            return result
        raise ValueError("unsupported expression")

    _WORD_OPERATORS = (
        (r"\bto the power of\b", "**"),
        (r"\bmultiplied by\b", "*"),
        (r"\bdivided by\b", "/"),
        (r"\bmodulo\b|\bmod\b", "%"),
        (r"\bplus\b", "+"),
        (r"\bminus\b", "-"),
        (r"\btimes\b", "*"),
        (r"\bover\b", "/"),
        (r"(?<=\d)\s*x\s*(?=\d)", "*"),
        (r"\^", "**"),
    )

    def _try_math(self, text: str) -> str | None:
        """
        Evaluate simple arithmetic found in natural language ("what is 12 times 7").

        Needs a real expression (number, operator, number); a lone number such as
        the "2020" in "capital of France in 2020" is not a calculation.
        """
        expr_text = text.lower()
        for pattern, symbol in self._WORD_OPERATORS:
            expr_text = re.sub(pattern, f" {symbol} ", expr_text)

        for candidate in re.findall(r"[\d.()+\-*/% ]+", expr_text):
            candidate = candidate.strip()
            if not re.search(r"\d\s*\)?\s*(\*\*|[-+*/%])\s*\(?\s*[-+]?\s*\d", candidate):
                continue
            try:
                value = self._safe_eval(ast.parse(candidate, mode="eval"))
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, MemoryError):
                continue
            if isinstance(value, float):
                value = round(value, 6)
                if value == int(value):
                    value = int(value)
            shown = re.sub(r"\s+", " ", candidate)
            return f"The result of {shown} is {value}, {self.config.get('user_name', 'Sir')}."
        return None

    def _retrieve_rag_context(self, user_input: str) -> str:
        """
        Retrieve top 3 similar past exchanges from RAG memory.
        Returns formatted context to inject into system prompt.
        """
        if not self.rag_enabled or self.rag_collection.count() == 0:
            return ""
        
        try:
            # Embed the user input
            user_embedding = self.embedding_model.encode(user_input).tolist()
            
            # Query the collection for top 3 similar exchanges
            results = self.rag_collection.query(
                query_embeddings=[user_embedding],
                n_results=max(1, min(3, self.rag_collection.count())),
                include=["documents", "metadatas"]
            )
            
            if not results["documents"] or not results["documents"][0]:
                return ""
            
            # Format the retrieved context
            context_parts = []
            for doc, metadata in zip(results["documents"][0], results["metadatas"][0]):
                context_parts.append(f"Q: {metadata.get('user_message', '')}\nA: {doc}")
            
            context = "\n\n".join(context_parts)
            logger.debug(f"Retrieved RAG context: {context[:100]}...")
            return context
        except Exception as e:
            logger.debug(f"Error retrieving RAG context: {e}")
            return ""

    def _store_rag_exchange(self, user_message: str, assistant_response: str):
        """
        Store a user-assistant exchange in RAG memory.
        """
        if not self.rag_enabled:
            return
        
        try:
            # Embed the user message
            user_embedding = self.embedding_model.encode(user_message).tolist()
            
            # Generate a unique ID based on timestamp
            exchange_id = f"exchange_{int(datetime.datetime.now().timestamp() * 1000)}"
            
            # Store the exchange with metadata
            self.rag_collection.add(
                ids=[exchange_id],
                embeddings=[user_embedding],
                documents=[assistant_response],
                metadatas=[{
                    "user_message": user_message,
                    "timestamp": datetime.datetime.now().isoformat()
                }]
            )
            logger.debug(f"Stored RAG exchange: {exchange_id}")
        except Exception as e:
            logger.debug(f"Error storing RAG exchange: {e}")

    

    def clear_memory(self):
        """Clear the conversation memory buffer and RAG memory."""
        self.memory.clear()
        logger.info("Conversation memory cleared.")
        
        # Clear RAG memory (ChromaDB collection)
        if self.rag_enabled:
            try:
                # Delete and recreate the collection to clear it
                self.chroma_client.delete_collection(name="nova_exchanges")
                self.rag_collection = self.chroma_client.get_or_create_collection(
                    name="nova_exchanges",
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info("RAG memory cleared.")
            except Exception as e:
                logger.warning(f"Failed to clear RAG memory: {e}")
