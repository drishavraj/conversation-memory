import json
from typing import Literal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update, or_, func
from .models import Knowledge, KnowledgeChange, Entry

ThemeName = Literal["personal", "side-projects", "office"]

class Correction(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    text: str | None = Field(default=None, min_length=1, max_length=10000)
    theme_id: ThemeName | None = None
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    certainty: Literal["tentative", "explicit"] | None = None
    status: Literal["active", "completed", "dismissed"] | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if not self.reason.strip():
            raise ValueError("Reason must not be blank")
        if "text" in self.model_fields_set and (self.text is None or not self.text.strip()):
            raise ValueError("Corrected text must not be blank")
        for field in ["certainty", "status"]:
            if field in self.model_fields_set and getattr(self,field) is None:
                raise ValueError(f"{field} cannot be null")
        if not (self.model_fields_set - {"expected_version", "reason"}):
            raise ValueError("Include a change")
        return self

def serialize(row):
    return {"id":row.id,"kind":row.kind,"text":row.text,"theme_id":row.theme_id,"certainty":row.certainty,"owner":row.owner,"due_date":row.due_date.isoformat() if row.due_date else None,"date_basis":row.date_basis,"status":row.status,"origin":row.origin,"version":row.version,"source_entry_id":row.entry_id,"evidence":row.evidence,"evidence_start":row.evidence_start,"evidence_end":row.evidence_end}

def router_for(authorize, db):
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @router.get("/actions")
    def actions(theme_id: ThemeName | None = None, status: Literal["active","completed","dismissed"] = "active", owner: str | None = None, limit: int = Query(50,ge=1,le=100), session=Depends(db)):
        query=select(Knowledge).where(Knowledge.kind=="action", Knowledge.status==status)
        if theme_id:
            query=query.where(Knowledge.theme_id==theme_id)
        if owner:
            query=query.where(Knowledge.owner==owner)
        return [serialize(r) for r in session.scalars(query.order_by(Knowledge.id).limit(limit))]

    @router.patch("/knowledge/{item_id}")
    def correct(item_id: str, payload: Correction, session=Depends(db)):
        item=session.get(Knowledge,item_id)
        if item is None:
            raise HTTPException(404,"Knowledge item not found")
        changes=payload.model_dump(exclude_unset=True,exclude={"expected_version","reason"})
        if changes.get("status")=="completed" and item.kind!="action":
            raise HTTPException(422,"Only actions can be completed")
        before=serialize(item)
        # Mark semantic edits as user corrections; completing an action preserves provenance.
        if set(changes)-{"status"}:
            changes["origin"]="user_corrected"
        if "due_date" in changes:
            changes["date_basis"]="explicit" if changes["due_date"] else "unknown"
        changes["version"]=payload.expected_version+1
        result=session.execute(update(Knowledge).where(Knowledge.id==item_id,Knowledge.version==payload.expected_version).values(**changes).execution_options(synchronize_session=False))
        if result.rowcount!=1:
            session.rollback()
            raise HTTPException(409,"Item changed; reload before editing")
        session.refresh(item)
        after=serialize(item)
        session.add(KnowledgeChange(knowledge_id=item_id,before_json=json.dumps(before),after_json=json.dumps(after),reason=payload.reason))
        session.get(Entry,item.entry_id).index_status="pending"
        session.get(Entry,item.entry_id).index_error=None
        session.commit()
        return after

    @router.get("/knowledge/{item_id}/history")
    def history(item_id: str, session=Depends(db)):
        if session.get(Knowledge,item_id) is None:
            raise HTTPException(404,"Knowledge item not found")
        rows=session.scalars(select(KnowledgeChange).where(KnowledgeChange.knowledge_id==item_id).order_by(KnowledgeChange.changed_at))
        return [{"before":json.loads(r.before_json),"after":json.loads(r.after_json),"reason":r.reason,"changed_at":r.changed_at} for r in rows]

    @router.get("/search")
    def search(q: str = Query(min_length=1,max_length=500), theme_id: ThemeName | None = None, limit: int = Query(20,ge=1,le=100), session=Depends(db)):
        term=q.strip().lower()
        if not term:
            raise HTTPException(422,"Search must not be blank")
        query=select(Knowledge,Entry).join(Entry,Entry.id==Knowledge.entry_id).where(Knowledge.status=="active",or_(func.lower(Knowledge.text).contains(term,autoescape=True),func.lower(Knowledge.evidence).contains(term,autoescape=True)))
        if theme_id:
            query=query.where(Knowledge.theme_id==theme_id)
        rows=session.execute(query.order_by(Entry.uploaded_at.desc(),Knowledge.id).limit(limit)).all()
        return {"query":q,"scope":theme_id or "all","retrieval":"keyword","results":[{**serialize(item),"source_title":entry.title,"event_at":entry.event_at,"source_url":f"/api/entries/{entry.id}"} for item,entry in rows]}

    return router
