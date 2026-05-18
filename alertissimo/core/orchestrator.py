# alertissimo/core/orchestrator.py

import logging
from typing import Optional

from alertissimo.core.schema import WorkflowIR, IRResult, ExecutionContext, ConfirmationStep

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO)


def run_ir(ir: WorkflowIR, initial_context: Optional[ExecutionContext] = None) -> IRResult:
    """
    Run workflow - orchestrator is just a simple loop.
    
    The orchestrator's ONLY job is to:
    1. Create result container
    2. Create context
    3. Loop through steps and execute them
    4. Handle confirmation failure (special case)
    5. Return results
    
    All logic about WHAT to update in results lives in the models.
    """
    logger.info(f"Running workflow: {ir.name}")
    
    # Create result container (models will fill this)
    result = IRResult()
    
    # Create or use existing context
    context = initial_context or ExecutionContext()
    
    # Execute steps in order
    for i, step in enumerate(ir.steps):
        step_name = step.__class__.__name__
        logger.info(f"Step {i+1}/{len(ir.steps)}: {step_name}")
        
        try:
            # Execute step - it knows how to update result
            step.execute(context, result)
            
            # Special handling: if confirmation fails, stop workflow
            if isinstance(step, ConfirmationStep):
                if not context.get("confirm_success", False):
                    logger.warning("Confirmation failed, stopping workflow")
                    break
                    
        except Exception as e:
            logger.error(f"Step {step_name} failed: {e}")
            # Future: add retry logic, error handling, etc.
            raise
    
    logger.info(f"Workflow completed with {len(result.__dict__)} result categories")
    return result


# Async version for future streaming support
async def run_ir_async(ir: WorkflowIR, initial_context: Optional[ExecutionContext] = None) -> IRResult:
    """
    Async version for future use with streaming data.
    Currently just wraps sync version.
    """
    # For now, just run sync version
    # Future: proper async execution with asyncio
    return run_ir(ir, initial_context)
