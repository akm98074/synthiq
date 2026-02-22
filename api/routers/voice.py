"""
Voice calibration endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.database import User, VoiceProfile
from models.schemas import VoiceProfileOut

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("", response_model=VoiceProfileOut | None)
async def get_voice_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return None
    return VoiceProfileOut(
        id=profile.id,
        sample_count=profile.sample_count,
        style_signature=profile.style_signature,
        updated_at=profile.updated_at,
    )


@router.post("/samples", response_model=VoiceProfileOut)
async def upload_voice_sample(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a writing sample (PDF, DOCX, or TXT) to build the voice profile.
    Full style extraction via Claude Sonnet 4.6 implemented in Phase 4.
    """
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = VoiceProfile(
            user_id=current_user.id,
            sample_count=1,
            style_signature=None,
        )
        db.add(profile)
    else:
        profile.sample_count += 1

    await db.flush()
    await db.refresh(profile)

    return VoiceProfileOut(
        id=profile.id,
        sample_count=profile.sample_count,
        style_signature=profile.style_signature,
        updated_at=profile.updated_at,
    )


@router.delete("", status_code=204)
async def delete_voice_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        await db.delete(profile)
