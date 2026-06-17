from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Set

from app.models.llm_utils import is_code_question, is_market_question
from app.services import runtime_metrics
from app.services.input_normalizer import (
    looks_like_url_candidate,
    normalize_for_routing,
    strip_attachment_context,
)

_VALID_MODES = {
    "general",
    "chat",
    "code",
    "web",
    "url",
    "crypto",
    "project",
    "image",
    "agent",
}


def _normalize_mode_value(raw_mode: str | None) -> str:
    value = normalize_for_routing(raw_mode or "chat")
    if not value:
        return "chat"
    mode = value.split()[0]
    if mode in {"general", "local"}:
        return "chat"
    return mode if mode in _VALID_MODES else "chat"


def validate_turn_inputs(
    *,
    message: str,
    mode_value: str,
    lang: str,
    active_project_id: str | None,
    crypto_symbol: str | None = None,
) -> Dict[str, Any] | None:
    """
    Validate user turn preconditions before routing and LLM synthesis.

    Returns a deterministic user-facing failure payload when validation fails.
    """
    mode = _normalize_mode_value(mode_value)
    text_norm = normalize_for_routing(message)

    if mode in {"web", "url"} and not text_norm:
        response = (
            "Modo web/url requiere una consulta. Ejemplo: `web: latest python release notes`."
            if lang.startswith("es")
            else "Web/URL mode requires a query. Example: `web: latest python release notes`."
        )
        return {"response": response, "tool_kind": "validation_web_query", "used_local": True}

    if mode == "url" and not looks_like_url_candidate(message):
        response = (
            "Modo URL requiere un enlace válido. Ejemplo: `url: https://docs.python.org/3/`."
            if lang.startswith("es")
            else "URL mode requires a valid link. Example: `url: https://docs.python.org/3/`."
        )
        return {"response": response, "tool_kind": "validation_url", "used_local": True}

    if mode == "project" and not str(active_project_id or "").strip():
        response = (
            "Modo proyecto requiere un proyecto activo. Activa uno y vuelve a intentar."
            if lang.startswith("es")
            else "Project mode requires an active project. Bind one and retry."
        )
        return {"response": response, "tool_kind": "validation_project", "used_local": True}

    if mode == "crypto":
        asks_crypto_detail = any(
            token in text_norm
            for token in (
                "predict",
                "prediction",
                "signal",
                "trade",
                "buy",
                "sell",
                "price",
                "ohlcv",
                "news",
                "prediccion",
                "predicción",
                "senal",
                "señal",
                "precio",
                "comprar",
                "vender",
            )
        )
        if asks_crypto_detail and not str(crypto_symbol or "").strip():
            response = (
                "Modo cripto requiere símbolo. Usa formato Binance como `BTCUSDT` (también `btc`, `eth`, `sol`). "
                "Quotes permitidos: USDT, USDC, BUSD, FDUSD, TUSD, BTC, ETH."
                if lang.startswith("es")
                else "Crypto mode requires a symbol. Use Binance format like `BTCUSDT` (also `btc`, `eth`, `sol`). "
                     "Allowed quote assets: USDT, USDC, BUSD, FDUSD, TUSD, BTC, ETH."
            )
            return {"response": response, "tool_kind": "validation_crypto_symbol", "used_local": True}

    return None


_GEO_QUESTION_PREFIXES = (
    "where is ",
    "where's ",
    "where are ",
    "where was ",
    "where were ",
    "donde esta ",
    "donde está ",
    "donde esta ",
    "donde esta ",
)

_CAPITAL_QUESTION_PREFIXES = (
    "what is the capital of ",
    "what's the capital of ",
    "which is the capital of ",
    "cuál es la capital de ",
    "cual es la capital de ",
)

_GEO_NON_GEO_HINTS = (
    "def ",
    "class ",
    "http",
    "https",
    "docker",
    "terraform",
    "sql",
    "import ",
)


def _looks_like_geography_question(message: str) -> bool:
    normalized = normalize_for_routing(strip_attachment_context(message)).lstrip("¿¡")
    if not normalized:
        return False
    if is_code_question(message) or is_market_question(message):
        return False
    if any(token in normalized for token in _GEO_NON_GEO_HINTS):
        return False
    return any(normalized.startswith(prefix) for prefix in _GEO_QUESTION_PREFIXES)


def _extract_geography_subject(message: str) -> str:
    normalized = normalize_for_routing(strip_attachment_context(message)).lstrip("¿¡")
    for prefix in _GEO_QUESTION_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        subject = normalized[len(prefix) :].strip(" ?.!,:;")
        return re.sub(r"\s+", " ", subject).strip()
    return ""


def _looks_like_capital_question(message: str) -> bool:
    normalized = normalize_for_routing(strip_attachment_context(message)).lstrip("¿¡")
    if not normalized:
        return False
    if is_code_question(message) or is_market_question(message):
        return False
    return any(normalized.startswith(prefix) for prefix in _CAPITAL_QUESTION_PREFIXES)


def _extract_capital_subject(message: str) -> str:
    normalized = normalize_for_routing(strip_attachment_context(message)).lstrip("¿¡")
    for prefix in _CAPITAL_QUESTION_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        subject = normalized[len(prefix) :].strip(" ?.!,:;")
        return re.sub(r"\s+", " ", subject).strip()
    return ""


def _looks_like_code_heavy_answer(text: str) -> bool:
    candidate = str(text or "")
    if not candidate.strip():
        return False
    if "```" in candidate:
        return True
    lower = candidate.lower()
    strong_tokens = (
        "import ",
        "def ",
        "class ",
        "pip install",
        "npm install",
        "flask",
        "fastapi",
        "angular",
        "sqlalchemy",
        "docker-compose",
        "@app.route",
    )
    token_hits = sum(1 for token in strong_tokens if token in lower)
    if token_hits >= 3:
        return True
    line_hits = 0
    for line in candidate.splitlines()[:80]:
        stripped = line.strip().lower()
        if re.match(r"^(from\s+\w+|import\s+\w+|def\s+\w+|class\s+\w+|@app\.route|ng\s+\w+|pip\s+install)", stripped):
            line_hits += 1
            if line_hits >= 4:
                return True
    return False


def _fold_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _local_geography_fact(subject: str, lang: str) -> str:
    normalized = normalize_for_routing(subject)
    if not normalized:
        return ""
    normalized = _fold_accents(normalized)
    facts_en = {
        "colombia": "Colombia is in the northwest of South America, between Panama, Venezuela, Brazil, Peru, and Ecuador, with coasts on the Caribbean Sea and the Pacific Ocean.",
        "russia": "Russia spans Eastern Europe and Northern Asia.",
        "usa": "The United States is a country in North America, bordering Canada and Mexico, with coasts on the Atlantic and Pacific Oceans.",
        "united states": "The United States is a country in North America, bordering Canada and Mexico, with coasts on the Atlantic and Pacific Oceans.",
        "brazil": "Brazil is the largest country in South America, sharing borders with every nation except Chile and Ecuador.",
        "argentina": "Argentina is in southern South America, bordering Chile, Bolivia, Paraguay, Brazil, and Uruguay.",
        "mexico": "Mexico is in southern North America, bordering the United States, Guatemala, and Belize.",
        "chile": "Chile is a long narrow country along South America's western coast, between Peru and Argentina.",
        "peru": "Peru is in western South America, bordering Ecuador, Colombia, Brazil, Bolivia, and Chile.",
        "spain": "Spain is in southwestern Europe on the Iberian Peninsula, bordering France and Portugal.",
        "france": "France is in western Europe, bordering Belgium, Germany, Italy, Spain, and Switzerland.",
        "germany": "Germany is in central Europe, bordering Denmark, Poland, Czechia, Austria, and France.",
        "japan": "Japan is an island nation in the Pacific Ocean, located east of China and Korea.",
        "italy": "Italy is a peninsula in southern Europe, bordering France, Switzerland, and Austria.",
        "india": "India is in South Asia, bordering Pakistan, China, Nepal, Bhutan, Bangladesh, and Myanmar.",
        "canada": "Canada is in northern North America, bordering the United States, with coasts on the Atlantic and Pacific.",
        "uk": "The United Kingdom is an island nation in northwestern Europe, comprising England, Scotland, Wales, and Northern Ireland.",
        "united kingdom": "The United Kingdom is an island nation in northwestern Europe, comprising England, Scotland, Wales, and Northern Ireland.",
        "china": "China is in East Asia, bordering 14 countries and having coasts on the East China Sea and South China Sea.",
        "australia": "Australia is a continent and country in the Southern Hemisphere, surrounded by the Indian and Pacific Oceans.",
        "egypt": "Egypt is in northeastern Africa, with a small Asian portion (Sinai), bordered by Libya, Sudan, and Israel.",
        "south africa": "South Africa is at the southern tip of Africa, bordering Namibia, Botswana, Zimbabwe, and Mozambique.",
    }
    facts_es = {
        "colombia": "Colombia está en el noroeste de Sudamérica, entre Panamá, Venezuela, Brasil, Perú y Ecuador, con costas en el mar Caribe y el océano Pacífico.",
        "russia": "Rusia se extiende entre Europa oriental y el norte de Asia.",
        "usa": "Estados Unidos es un país en América del Norte, fronterizo con Canadá y México, con costas en los océanos Atlántico y Pacífico.",
        "united states": "Estados Unidos es un país en América del Norte, fronterizo con Canadá y México, con costas en los océanos Atlántico y Pacífico.",
        "brazil": "Brasil es el país más grande de Sudamérica,-limita con todas las naciones excepto Chile y Ecuador.",
        "argentina": "Argentina está en el sur de Sudamérica, fronteriza con Chile, Bolivia, Paraguay, Brasil y Uruguay.",
        "mexico": "México está en el norte de América del Sur, fronterizo con Estados Unidos, Guatemala y Belice.",
        "chile": "Chile es un país largo y estrecho a lo largo de la costa occidental de Sudamérica, entre Perú y Argentina.",
        "peru": "Perú está en el oeste de Sudamérica, fronterizo con Ecuador, Colombia, Brasil, Bolivia y Chile.",
        "spain": "España está en el suroeste de Europa en la Península Ibérica, fronteriza con Francia y Portugal.",
        "france": "Francia está en Europa occidental, fronteriza con Bélgica, Alemania, Italia, España y Suiza.",
        "germany": "Alemania está en el centro de Europa, fronteriza con Dinamarca, Polonia, República Checa, Austria y Francia.",
        "japan": "Japón es una nación insular en el Océano Pacífico, ubicada al este de China y Corea.",
        "italy": "Italia es una península en el sur de Europa, fronteriza con Francia, Suiza y Austria.",
        "india": "India está en el sur de Asia, fronteriza con Pakistán, China, Nepal, Bután, Bangladesh y Myanmar.",
        "canada": "Canadá está en el norte de América del Norte, fronterizo con Estados Unidos, con costas en los océanos Atlántico y Pacífico.",
        "uk": "El Reino Unido es una nación insular en el norte de Europa, comprende Inglaterra, Escocia, Gales e Irlanda del Norte.",
        "united kingdom": "El Reino Unido es una nación insular en el norte de Europa, comprende Inglaterra, Escocia, Gales e Irlanda del Norte.",
        "china": "China está en el Este de Asia, fronteriza con 14 países y tiene costas en el Mar del Este de China y el Mar del Sur de China.",
        "australia": "Australia es un continente y país en el Hemisferio Sur, rodeado por los océanos Índico y Pacífico.",
        "egypt": "Egipto está en el noreste de África, con una pequeña porción asiática (Sinai), fronteriza con Libia, Sudán e Israel.",
        "south africa": "Sudáfrica está en el extremo sur de África, fronteriza con Namibia, Botsuana, Zimbabue y Mozambique.",
    }
    for key, text in (facts_es.items() if lang.startswith("es") else facts_en.items()):
        if normalized == key or normalized.startswith(f"{key} ") or f" {key} " in f" {normalized} ":
            return text
    return ""


_COUNTRY_CAPITALS: Dict[str, Dict[str, str]] = {
    "argentina": {"en": "Buenos Aires", "es": "Buenos Aires"},
    "brazil": {"en": "Brasília", "es": "Brasilia"},
    "brasil": {"en": "Brasília", "es": "Brasilia"},
    "canada": {"en": "Ottawa", "es": "Ottawa"},
    "chile": {"en": "Santiago", "es": "Santiago"},
    "colombia": {"en": "Bogotá", "es": "Bogotá"},
    "france": {"en": "Paris", "es": "París"},
    "francia": {"en": "Paris", "es": "París"},
    "germany": {"en": "Berlin", "es": "Berlín"},
    "alemania": {"en": "Berlin", "es": "Berlín"},
    "india": {"en": "New Delhi", "es": "Nueva Delhi"},
    "italy": {"en": "Rome", "es": "Roma"},
    "japan": {"en": "Tokyo", "es": "Tokio"},
    "japon": {"en": "Tokyo", "es": "Tokio"},
    "mexico": {"en": "Mexico City", "es": "Ciudad de México"},
    "peru": {"en": "Lima", "es": "Lima"},
    "russia": {"en": "Moscow", "es": "Moscú"},
    "rusia": {"en": "Moscow", "es": "Moscú"},
    "spain": {"en": "Madrid", "es": "Madrid"},
    "espana": {"en": "Madrid", "es": "Madrid"},
    "united kingdom": {"en": "London", "es": "Londres"},
    "reino unido": {"en": "London", "es": "Londres"},
    "united states": {"en": "Washington, D.C.", "es": "Washington, D.C."},
    "usa": {"en": "Washington, D.C.", "es": "Washington, D.C."},
    "estados unidos": {"en": "Washington, D.C.", "es": "Washington, D.C."},
    "estados unidos de america": {"en": "Washington, D.C.", "es": "Washington, D.C."},
    "russia": {"en": "Moscow", "es": "Moscú"},
    "spain": {"en": "Madrid", "es": "Madrid"},
    "united kingdom": {"en": "London", "es": "Londres"},
    "uk": {"en": "London", "es": "Londres"},
    "united states": {"en": "Washington, D.C.", "es": "Washington, D.C."},
    "usa": {"en": "Washington, D.C.", "es": "Washington, D.C."},
}


def _local_capital_fact(subject: str, lang: str) -> str:
    normalized = normalize_for_routing(subject)
    if not normalized:
        return ""
    normalized = _fold_accents(normalized)
    if normalized.startswith("the "):
        normalized = normalized[4:].strip()
    for key, payload in _COUNTRY_CAPITALS.items():
        if normalized == key or normalized.startswith(f"{key} ") or f" {key} " in f" {normalized} ":
            name = payload["es"] if lang.startswith("es") else payload["en"]
            if lang.startswith("es"):
                return f"La capital de {subject.strip()} es {name}."
            return f"The capital of {subject.strip()} is {name}."
    return ""


def maybe_local_geography_response(
    user_message: str,
    lang: str,
    *,
    explicit_web: bool = False,
    explicit_url: bool = False,
) -> str:
    if explicit_web or explicit_url:
        return ""
    if not _looks_like_geography_question(user_message):
        return ""

    subject = _extract_geography_subject(user_message)
    fact = _local_geography_fact(subject, lang)
    if not fact:
        return ""

    hint = (
        "Si quieres fuentes en vivo, usa `web: where is <place>`."
        if lang.startswith("es")
        else "If you want live sources, use `web: where is <place>`."
    )
    return f"{fact}\n\n{hint}"


def maybe_local_capital_response(
    user_message: str,
    lang: str,
    *,
    explicit_web: bool = False,
    explicit_url: bool = False,
) -> str:
    if explicit_web or explicit_url:
        return ""
    if not _looks_like_capital_question(user_message):
        return ""

    subject = _extract_capital_subject(user_message)
    fact = _local_capital_fact(subject, lang)
    if not fact:
        return ""

    hint = (
        "Si quieres fuentes en vivo, usa `web: what is the capital of <country>`."
        if lang.startswith("es")
        else "If you want live sources, use `web: what is the capital of <country>`."
    )
    return f"{fact}\n\n{hint}"


def _extract_framework_claims(text: str) -> Set[str]:
    if not text:
        return set()
    text_lower = str(text).lower()
    candidates = {"fastapi", "flask", "django", "starlette", "bottle", "pyramid", "falcon", "sanic", "tornado"}
    claims: Set[str] = set()
    for candidate in candidates:
        if re.search(rf"\b(?:uses|using|built with|based on|running on|powered by|framework(?: is|:)?|uses the|is a)\s+{re.escape(candidate)}\b", text_lower):
            claims.add(candidate)
        elif re.search(rf"\b{re.escape(candidate)}\s+(?:application|app|project|server|service)\b", text_lower):
            claims.add(candidate)
    return claims


def _extract_project_file_claims(text: str) -> Set[str]:
    if not text:
        return set()
    text_lower = str(text).lower()
    mentions = set()
    matches = re.findall(r"\b[a-z0-9_./-]+\.(?:py|toml|txt)\b", text_lower)
    if "dockerfile" in text_lower:
        matches.append("dockerfile")
    for match in matches:
        if re.search(rf"(?:file|files|module|script|path|located at|found at|in )\s+{re.escape(match)}\b", text_lower) or re.search(rf"\b{re.escape(match)}\s+(?:is|exists|contains|should be)\b", text_lower):
            mentions.add(match)
    return mentions


def _manifest_evidence_failure(claim: str, lang: str) -> str:
    if lang.startswith("es"):
        return (
            f"No hay evidencia en el manifiesto del proyecto para `{claim}`. "
            "Revisa el proyecto o usa `web:` para información más segura."
        )
    return (
        f"There is no evidence in the project manifest for `{claim}`. "
        "Check the project or use `web:` for safer information."
    )


def apply_output_quality_guard(
    *,
    user_message: str,
    response_text: str,
    lang: str,
    source_plan: str,
    web_meta: Dict[str, Any] | None,
    project_manifest: Dict[str, Any] | None = None,
) -> str:
    """
    Prevent clearly off-topic answers and redirect geography questions away from code-style replies.
    """
    response = str(response_text or "").strip()
    if not response:
        return response

    if isinstance(project_manifest, dict):
        for framework in _extract_framework_claims(response):
            if not check_framework_exists(framework, project_manifest):
                try:
                    runtime_metrics.record_safety_fallback("manifest_evidence_guard")
                except Exception:
                    pass
                return _manifest_evidence_failure(framework, lang)
        for file_claim in _extract_project_file_claims(response):
            if not check_file_exists_in_manifest(file_claim, project_manifest):
                try:
                    runtime_metrics.record_safety_fallback("manifest_evidence_guard")
                except Exception:
                    pass
                return _manifest_evidence_failure(file_claim, lang)

    if not _looks_like_geography_question(user_message) and not _looks_like_capital_question(user_message):
        return response
    if not _looks_like_code_heavy_answer(response):
        return response

    subject = _extract_geography_subject(user_message) or _extract_capital_subject(user_message)
    fact = _local_geography_fact(subject, lang) or _local_capital_fact(subject, lang)
    meta = dict(web_meta or {})
    web_source = str(meta.get("source") or "").strip().lower()
    web_status = str(meta.get("status") or "").strip().lower()
    web_unavailable = source_plan in {"web_only", "local+web"} and (web_source in {"", "none"} or web_status in {"error", "unavailable"})

    if fact:
        reason = (
            "Descarté una respuesta fuera de tema (código) y respondí tu pregunta geográfica de forma directa."
            if lang.startswith("es")
            else "I dropped an off-topic code-style draft and answered your geography question directly."
        )
        if web_unavailable:
            reason += (
                " La evidencia web no estuvo disponible en este turno; usé contexto local."
                if lang.startswith("es")
                else " Web evidence was unavailable in this turn, so I used local context."
            )
        try:
            runtime_metrics.record_safety_fallback("off_topic_guard")
        except Exception:
            pass
        return f"{fact}\n\n{reason}"

    fallback = (
        "Tu pregunta es geográfica, no de código. Reformúlala como `web: where is <place>` para forzar web en vivo, o indica el lugar exacto."
        if lang.startswith("es")
        else "Your question is geographic, not a coding task. Rephrase as `web: where is <place>` to force live web, or provide the exact place."
    )
    if web_unavailable:
        fallback += (
            " En este turno no hubo evidencia web disponible."
            if lang.startswith("es")
            else " Web evidence was unavailable in this turn."
        )
    try:
        runtime_metrics.record_safety_fallback("off_topic_guard")
    except Exception:
        pass
    return fallback


def check_framework_exists(framework: str, manifest: Dict[str, Any] | None) -> bool:
    """Check whether a framework token is declared in a project manifest."""
    if not framework or not isinstance(manifest, dict):
        return False
    frameworks = [str(f).lower() for f in (manifest.get("frameworks") or []) if isinstance(f, str)]
    return str(framework).lower() in frameworks


def check_file_exists_in_manifest(path: str, manifest: Dict[str, Any] | None) -> bool:
    """Simple existence check in manifest's `file_tree`."""
    if not path or not isinstance(manifest, dict):
        return False
    tree = [str(p) for p in (manifest.get("file_tree") or [])]
    return any(str(path).strip() == t.strip() or t.strip().endswith(str(path).strip()) for t in tree)


def check_entrypoint_exists(route: str, manifest: Dict[str, Any] | None) -> bool:
    """Check common entrypoints list for a matching route or path."""
    if not route or not isinstance(manifest, dict):
        return False
    entrypoints = [str(p) for p in (manifest.get("entrypoints") or [])]
    # direct match or substring
    return any(route.strip() == ep.strip() or route.strip() in ep for ep in entrypoints)
