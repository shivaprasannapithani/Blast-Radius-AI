
import os
import re

import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Blast Radius AI",
    page_icon="🕸️",
    layout="wide",
)

st.title("🕸️ Blast Radius AI")
st.caption(
    "Graph-powered incident investigation with explicit evidence paths"
)


def api_get(path, timeout=5):
    response = requests.get(f"{API}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_post(path, payload, timeout=30):
    return requests.post(
        f"{API}{path}",
        json=payload,
        timeout=timeout,
    )


def show_answer(answer):
    """Preserve line breaks and Markdown lists in the agent response."""
    if not answer:
        st.info("The agent did not return a text summary.")
        return

    # Preserve line breaks so adjacent sections do not run together.
    formatted = answer.replace("\r\n", "\n")
    formatted = re.sub(r"(?<!\n)\n(?!\n)", "  \n", formatted)
    st.markdown(formatted)


def show_investigation(data):
    answer = data.get("answer", "")
    tool_results = data.get("tool_results", [])

    st.subheader("Investigation summary")
    show_answer(answer)

    # Extract the impacted count when the answer includes it.
    match = re.search(
        r"found\s+(\d+)\s+impacted service",
        answer,
        re.IGNORECASE,
    )

    st.divider()
    st.subheader("Investigation overview")

    metric1, metric2, metric3 = st.columns(3)

    metric1.metric("Incident service", data.get("service", "Unknown"))
    metric2.metric(
        "Impacted services",
        match.group(1) if match else "See summary",
    )
    metric3.metric("Evidence tools", len(tool_results))

    st.subheader("Evidence and graph paths")

    if not tool_results:
        st.info("No tool evidence was returned for this investigation.")

    for item in tool_results:
        tool_name = item.get("tool", "Investigation tool")
        result = item.get("result", {})

        with st.expander(
            tool_name.replace("_", " ").title(),
            expanded=False,
        ):
            if isinstance(result, dict):
                st.json(result)
            else:
                st.write(result)

    with st.expander("Full API response", expanded=False):
        st.json(data)


# Sidebar: backend health
with st.sidebar:
    st.header("System status")

    try:
        health = api_get("/health", timeout=3)
        st.success(
            f"API: {health.get('status', 'unknown')} · "
            f"DB: {health.get('database', 'unknown')}"
        )
    except (requests.RequestException, ValueError):
        st.error("API unavailable. Start the FastAPI server first.")

    try:
        service_data = api_get("/services")
        services = service_data.get("services", [])
        names = [
            item["name"]
            for item in services
            if isinstance(item, dict) and item.get("name")
        ]
    except (requests.RequestException, ValueError, AttributeError):
        names = []

    st.divider()
    st.header("Investigation settings")

    service_options = names or ["payments-api"]

    service = st.selectbox(
        "Incident service",
        service_options,
    )

    depth = st.slider(
        "Dependency depth",
        min_value=1,
        max_value=5,
        value=3,
    )

    st.caption(
        "Depth is capped server-side. "
        "An empty result means no modeled path was found."
    )


# Main investigation
st.subheader("Investigate an incident")

question = st.text_area(
    "What happened?",
    value=(
        "payments-api is down. What is affected, "
        "who should respond, and what changed recently?"
    ),
    height=100,
)

if st.button(
    "🔍 Investigate incident",
    type="primary",
    use_container_width=True,
):
    if not question.strip():
        st.warning("Enter a question before investigating.")
    else:
        try:
            with st.spinner("Traversing service graph..."):
                response = api_post(
                    "/investigate",
                    {
                        "question": question,
                        "service": service,
                        "depth": depth,
                    },
                    timeout=60,
                )

            try:
                data = response.json()
            except ValueError:
                data = {"detail": response.text}

            if response.ok:
                if data.get("answer"):
                    show_investigation(data)
                else:
                    st.warning("The API returned no investigation summary.")
                    st.json(data)
            else:
                st.error(f"Investigation failed ({response.status_code})")
                st.json(data)

        except requests.RequestException as exc:
            st.error(f"Could not reach the API: {exc}")


st.divider()

left, right = st.columns(2)

# Dependency path tracing
with left:
    st.subheader("🔗 Trace a dependency path")
    st.caption("Trace a consumer service to a provider service.")

    source = st.selectbox(
        "Consumer / source",
        service_options,
        key="source",
    )

    target = st.selectbox(
        "Provider / target",
        service_options,
        index=min(2, len(service_options) - 1),
        key="target",
    )

    if st.button("Find dependency path", use_container_width=True):
        try:
            with st.spinner("Searching dependency graph..."):
                response = api_post(
                    "/path",
                    {"source": source, "target": target},
                    timeout=15,
                )

            if response.ok:
                path_data = response.json()
                st.json(path_data)

                path = path_data.get("path", [])
                if path:
                    st.markdown("**Dependency route**")
                    st.markdown(" → ".join(path))
            else:
                st.error(f"Path query failed ({response.status_code})")
                st.text(response.text)

        except requests.RequestException as exc:
            st.error(f"Could not query dependency path: {exc}")


# Save investigation findings
with right:
    st.subheader("📝 Save an investigation finding")
    st.caption("Store a useful finding or postmortem note in graph memory.")

    finding_service = st.selectbox(
        "Service for memory",
        service_options,
        key="finding_service",
    )

    finding_text = st.text_area(
        "Finding / postmortem note",
        key="finding_text",
        height=100,
    )

    session = st.text_input(
        "Session / incident ID",
        value="postmortem-demo",
    )

    if st.button("Save finding", use_container_width=True):
        if not finding_text.strip():
            st.warning("Enter a finding before saving.")
        else:
            try:
                response = api_post(
                    "/findings",
                    {
                        "service": finding_service,
                        "text": finding_text,
                        "session": session,
                    },
                    timeout=15,
                )

                if response.ok:
                    st.success("Finding saved to graph memory.")
                    st.json(response.json())
                else:
                    st.error(f"Save failed ({response.status_code})")
                    st.text(response.text)

            except requests.RequestException as exc:
                st.error(f"Could not save finding: {exc}")


st.divider()
st.caption(
    "Blast Radius AI · Graph-based investigation · "
    "Correlations are not proof of causation."
)
