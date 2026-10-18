from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from app.agent import IncidentAgent
from app.tools import IncidentTools, UnknownService
from app.graph_store import get_store

app = FastAPI(title="Blast Radius AI", version="1.0.0", description="Explainable graph-powered service incident investigation")

class InvestigateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    service: str | None = Field(default=None, max_length=100)
    depth: int = Field(default=3, ge=1, le=5)
class PathRequest(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
class FindingRequest(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    session: str = Field(default="manual", max_length=100)

@app.get("/health")
def health():
    try: ok = get_store().ping()
    except Exception: ok = False
    return {"status": "ok" if ok else "degraded", "database": "connected" if ok else "unavailable"}

@app.get("/services")
def services():
    try: return IncidentTools().list_services()
    except Exception as e: raise HTTPException(503, f"Graph database unavailable: {e}")

@app.post("/investigate")
def investigate(req: InvestigateRequest):
    try: return IncidentAgent().investigate(req.question, req.service, req.depth)
    except UnknownService as e: raise HTTPException(404, {"outcome":"unknown_service", "detail":str(e), "tool_results":[]})
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(503, f"Investigation failed: {e}")

@app.post("/path")
def path(req: PathRequest):
    try: return IncidentTools().path_between(req.source, req.target)
    except UnknownService as e: raise HTTPException(404, {"outcome":"unknown_service", "detail":str(e)})
    except Exception as e: raise HTTPException(503, f"Graph query failed: {e}")

@app.post("/findings")
def save_finding(req: FindingRequest):
    try: return IncidentTools().save_finding(req.service, req.text, req.session)
    except UnknownService as e: raise HTTPException(404, str(e))
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(503, f"Could not save finding: {e}")

@app.get("/findings/{service}")
def recall(service: str):
    try: return IncidentTools().recall(service)
    except UnknownService as e: raise HTTPException(404, str(e))
    except Exception as e: raise HTTPException(503, f"Could not read findings: {e}")
