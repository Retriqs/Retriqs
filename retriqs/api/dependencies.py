from fastapi import Path, HTTPException, Request
from retriqs import LightRAG
from retriqs.utils import logger

async def get_rag_by_id(request: Request, storage_id: int = Path(...,description="The ID of the storage to use")) -> LightRAG:
    manager = request.app.state.rag_manager
    
    if not manager:
        raise HTTPException(status_code=500, detail="RAG Manager not initialized")
    
    instance = manager.get_instance(storage_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Storage {storage_id} not found")
    
    logger.info(f"[get_rag_by_id] storage_id={storage_id} -> working_dir={instance.working_dir}, workspace={instance.workspace}")
    
    return instance

