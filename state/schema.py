from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"
    PENDING = "pending"

class RawStory(BaseModel):
    headline: str
    url: str
    source: str
    raw_summary: str
    scraped_at: str  # ISO timestamp

class VerifiedStory(RawStory):
    verification_status: VerificationStatus
    confidence_score: float  # 0.0 to 1.0
    supporting_sources: list[str]
    verification_notes: str

class ResearchedStory(VerifiedStory):
    background_context: str       # History, prerequisites
    key_players: list[str]        # Companies, people involved
    related_stories: list[str]    # URLs of related past events
    significance: str             # Why this matters

class WrittenStory(ResearchedStory):
    mini_article: str             # ~300 word article for this story
    x_thread: list[str]           # List of tweet strings (280 chars each)
    linkedin_snippet: str         # 150-char teaser for LinkedIn

class NewsAgentState(BaseModel):
    """Full shared state passed between all agents in the graph."""
    
    # Configuration
    target_stories: int = 10
    
    # Pipeline stage tracking
    current_stage: str = "init"
    error_log: list[str] = Field(default_factory=list)
    
    # Data at each stage
    raw_stories: list[RawStory] = Field(default_factory=list)
    verified_stories: list[VerifiedStory] = Field(default_factory=list)
    researched_stories: list[ResearchedStory] = Field(default_factory=list)
    written_stories: list[WrittenStory] = Field(default_factory=list)
    
    # Final outputs
    full_blog_post: Optional[str] = None
    linkedin_post: Optional[str] = None
    x_thread_full: Optional[list[str]] = None
    
    # Publishing status
    published_to_x: bool = False
    published_to_linkedin: bool = False
