"""Safe tool-selection agent with deterministic fallback and optional OpenAI-compatible LLM."""
import json
from app.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from app.tools import IncidentTools, UnknownService

SYSTEM = """You are Blast Radius AI, an SRE incident investigation assistant. Use only the supplied fixed tools. Never invent services, owners, changes, or evidence. Treat change timing as correlation, not proof. State when graph coverage is incomplete. Return concise, actionable answers with paths."""

class IncidentAgent:
    def __init__(self, tools: IncidentTools | None = None):
        self.tools = tools or IncidentTools()

    def investigate(self, question: str, service: str | None = None, depth: int = 3) -> dict:
        if not question.strip() or len(question) > 2000:
            raise ValueError("Question must contain 1–2000 characters.")
        selected = service or self._extract_service(question)
        if not selected:
            return {"answer": "Please specify a service name, for example: 'payments-api is down. What is affected?'", "tool_results": [], "mode": "deterministic"}
        # Resolve first. Unknown names stop here, before any other tool runs.
        canonical = self.tools.resolve_service(selected)
        q = question.lower()
        results = []
        if any(word in q for word in ("change", "deploy", "deployment", "recently", "what changed")):
            results.append({"tool": "recent_changes", "result": self.tools.recent_changes(canonical, 168, depth)})
        if any(word in q for word in ("who", "team", "on-call", "oncall", "wake", "owner", "respond")):
            results.append({"tool": "who_to_wake", "result": self.tools.who_to_wake(canonical, depth)})
        if any(word in q for word in ("previous", "before", "memory", "history", "remember", "last incident")):
            results.append({"tool": "recall", "result": self.tools.recall(canonical)})
        if not results or any(word in q for word in ("impact", "affect", "break", "down", "blast", "incident", "outage")):
            results.append({"tool": "blast_radius", "result": self.tools.blast_radius(canonical, depth)})
        answer = self._compose(canonical, results)
        mode = "deterministic"
        if LLM_BASE_URL and LLM_API_KEY and LLM_MODEL:
            try:
                answer = self._llm_answer(question, results)
                # Grounding guard: don't let the LLM add service names absent from graph evidence.
                known = {canonical}
                for item in results:
                    data = item["result"]
                    for x in data.get("impacted_services", []): known.add(x["service"]); known.update(x.get("path", []))
                    for x in data.get("owners", []): known.add(x["service"])
                    for x in data.get("changes", []): known.add(x["service"])
                tokens = {part for part in answer.replace("`", " ").replace(",", " ").replace(".", " ").split() if "-" in part and part.lower() == part}
                if tokens - known:
                    answer = self._compose(canonical, results)
                    mode = "deterministic_fallback_grounding_check"
                else:
                    mode = "llm_with_graph_evidence"
            except Exception:
                answer = self._compose(canonical, results)
                mode = "deterministic_fallback_llm_error"
        return {"answer": answer, "service": canonical, "tool_results": results, "mode": mode}

    def _extract_service(self, question: str) -> str | None:
        names = [x["name"] for x in self.tools.list_services()["services"]]
        q = question.lower()
        matches = [n for n in names if n.lower() in q]
        return max(matches, key=len) if matches else None

    def _compose(self, service: str, results: list[dict]) -> str:
        lines = [f"Incident focus: {service}."]
        for item in results:
            name, data = item["tool"], item["result"]
            if name == "blast_radius":
                if data["impacted_services"]:
                    lines.append(f"Graph traversal found {data['impacted_count']} impacted service(s):")
                    for x in data["impacted_services"]:
                        lines.append(f"- {x['service']} (tier {x['tier']}, {x['hops']} hop(s)): {' -> '.join(x['path'])}")
                else: lines.append(data.get("note") or "No impacted services were found in the current graph.")
            elif name == "who_to_wake":
                if data["owners"]:
                    lines.append("Ownership / response contacts:")
                    for x in data["owners"]: lines.append(f"- {x['service']}: {x['team']} (responders: {', '.join(x['responders']) or 'not recorded'})")
                else: lines.append("No owners are recorded for the services checked.")
            elif name == "recent_changes":
                lines.append("Recent changes (correlation, not proof of cause):")
                if data["changes"]:
                    for x in data["changes"]: lines.append(f"- {x['at']} {x['sha']} {x['service']}: {x['summary']} by {x['author']}")
                else: lines.append("No changes matched the requested time window.")
            elif name == "recall":
                lines.append("Prior findings:")
                if data["findings"]:
                    for x in data["findings"]: lines.append(f"- [{x['at']}] {x['text']} (session: {x['session']})")
                else: lines.append("No prior findings are stored for this service.")
        lines.append("Caveat: conclusions are limited to relationships and records currently modeled in the graph.")
        return "\n".join(lines)

    def _llm_answer(self, question: str, results: list[dict]) -> str:
        from openai import OpenAI
        client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
        response = client.chat.completions.create(model=LLM_MODEL, temperature=0.1,
            messages=[{"role":"system","content":SYSTEM}, {"role":"user","content":json.dumps({"question":question,"graph_evidence":results})}])
        content = response.choices[0].message.content
        if not content: raise RuntimeError("LLM returned empty content")
        return content.strip()
