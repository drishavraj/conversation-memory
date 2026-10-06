"""Explicit, immutable workspace sessions. Never derive tenant scope from request data."""
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy import event, select, text, inspect
from sqlalchemy.orm import Session, with_loader_criteria, sessionmaker
from .models import WorkspaceOwned, Workspace, WorkspaceMembership, WorkspaceAISettings, Theme

@dataclass(frozen=True)
class Access:
    workspace_id: str
    user_id: str | None = None

class WorkspaceSession(Session):
    def __init__(self,*args,access:Access,**kwargs):
        super().__init__(*args,**kwargs)
        self._access=access
        UUID(access.workspace_id)
    @property
    def access(self):return self._access
    def get(self,entity,ident,**kwargs):
        row=super().get(entity,ident,**kwargs)
        if row is not None and hasattr(row,'workspace_id') and row.workspace_id!=self.access.workspace_id:
            raise RuntimeError('Cross-workspace identity map access')
        return row


def workspace_sessions(engine,workspace_id,user_id=None):
    return sessionmaker(engine,class_=WorkspaceSession,access=Access(workspace_id,user_id),expire_on_commit=False)

@event.listens_for(WorkspaceSession,'after_begin')
def transaction_context(session,transaction,connection):
    if transaction.nested:return
    a=session.access
    if connection.dialect.name=='postgresql':
        connection.execute(text("SELECT set_config('app.workspace_id', :w, true)"),{'w':a.workspace_id})
    active=connection.execute(select(Workspace.id).where(Workspace.id==a.workspace_id,Workspace.status=='active')).scalar_one_or_none()
    if not active:raise PermissionError('Workspace is not active')
    if a.user_id is not None:
        member=connection.execute(select(WorkspaceMembership.user_id).where(WorkspaceMembership.workspace_id==a.workspace_id,WorkspaceMembership.user_id==a.user_id,WorkspaceMembership.status=='active')).scalar_one_or_none()
        if not member:raise PermissionError('Workspace access revoked')

@event.listens_for(WorkspaceSession,'do_orm_execute')
def scope_statement(state):
    if not state.is_orm_statement or state.is_insert:
        raise RuntimeError('Workspace sessions require ORM reads/updates/deletes; use add for inserts')
    wid=state.session.access.workspace_id
    if state.is_update:
        values=getattr(state.statement,'_values',{}) or {}
        if any(getattr(key,'key',str(key))=='workspace_id' or getattr(key,'key',str(key)).endswith('_id') for key in values):
            raise RuntimeError('Workspace ownership is immutable')
    allowed=(WorkspaceOwned,WorkspaceAISettings,Theme)
    for mapper in state.all_mappers:
        if not issubclass(mapper.class_,allowed):raise RuntimeError('Administrative table unavailable in workspace session')
        if (state.is_update or state.is_delete) and mapper.class_ is Theme:raise RuntimeError('Shared themes are read-only')
    state.statement=state.statement.options(
        with_loader_criteria(WorkspaceOwned,lambda cls:cls.workspace_id==wid,include_aliases=True),
        with_loader_criteria(WorkspaceAISettings,lambda cls:cls.workspace_id==wid,include_aliases=True))

@event.listens_for(WorkspaceSession,'before_flush')
def own_writes(session,context,instances):
    wid=session.access.workspace_id
    for row in session.new|session.dirty|session.deleted:
        if not isinstance(row,(WorkspaceOwned,WorkspaceAISettings)):
            raise RuntimeError('Administrative write denied')
        if row in session.new and row.workspace_id is None:row.workspace_id=wid
        if row.workspace_id!=wid or inspect(row).attrs.workspace_id.history.deleted:
            raise RuntimeError('Workspace ownership is immutable')
        if row not in session.deleted:validate_references(session,row)


def validate_references(session,row):
    """Validate embedded references on writes; evidence snapshots cannot cross tenants."""
    from .models import Entry,Knowledge
    from .memory_models import Topic,MemoryRecord,ChatTurn
    def require(model,id):
        if id and session.get(model,id) is None:raise ValueError('Reference outside workspace')
    for id in getattr(row,'topic_ids',[]) or []:require(Topic,id)
    def evidence(items):
        for item in items or []:
            require(Entry,item.get('source_entry_id'))
            # Memory evidence uses knowledge IDs; response sources use memory IDs.
            require(Knowledge,item.get('id'))
    if hasattr(row,'evidence') and isinstance(row.evidence,list):evidence(row.evidence)
    payload=getattr(row,'payload',None) or {}
    require(MemoryRecord,payload.get('target_id'))
    for id in payload.get('topic_ids',[]):require(Topic,id)
    for snapshot in (getattr(row,'before',None),getattr(row,'after',None)):
        if isinstance(snapshot,dict):
            for id in snapshot.get('topic_ids',[]):require(Topic,id)
            evidence(snapshot.get('evidence',[]))
    pending=getattr(row,'pending_turn_id',None)
    if pending:
        turn=session.get(ChatTurn,pending)
        if turn is None or turn.thread_id!=row.id:raise ValueError('Invalid pending turn')
    response=getattr(row,'response',None) or {}
    for source in response.get('sources',[]):
        require(MemoryRecord,source.get('id'));evidence(source.get('evidence',[]))


def active_workspaces(engine):
    # Scheduler control-plane access only: never reads recordings or derived content.
    with engine.connect() as conn:
        return list(conn.scalars(select(Workspace.id).where(Workspace.status=='active').order_by(Workspace.id)))


def across_workspaces(task,sessions,*args,**kwargs):
    if issubclass(sessions.class_,WorkspaceSession):return task(sessions,*args,**kwargs)
    engine=sessions.kw['bind']
    processed=False
    for wid in active_workspaces(engine):
        processed=bool(task(workspace_sessions(engine,wid),*args,**kwargs)) or processed
    return processed


def runtime_isolation_ready(engine):
    """Additional PostgreSQL deployment gate before admitting non-owner testers."""
    if engine.dialect.name!='postgresql':return True
    with engine.connect() as conn:
        privileged=conn.execute(text('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user')).scalar_one()
        if privileged:return False
        # Use metadata rather than ORM subclasses for table names.
        from .models import Base
        tables=[t.name for t in Base.metadata.tables.values() if 'workspace_id' in t.c and t.name not in ('workspace_memberships',)]
        for table in tables:
            row=conn.execute(text("SELECT c.relrowsecurity,c.relforcerowsecurity,pg_has_role(current_user,c.relowner,'MEMBER') AS owner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=:t"),{'t':table}).one()
            if row.owner or not row.relrowsecurity or not row.relforcerowsecurity:return False
        return True
