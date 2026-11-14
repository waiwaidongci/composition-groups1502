from sqlalchemy import String,Text,JSON,ForeignKey,Double,Integer
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now
class CompositionRun(Base):
    __tablename__="composition_runs"
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(160))
    study_id:Mapped[int]=mapped_column(ForeignKey("composition_studies.id"))
    delta:Mapped[float]=mapped_column(Double(asdecimal=False))
    permutations:Mapped[int]
    seed:Mapped[int]
    input_snapshot:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(24),default="queued")
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(Text,default="")
    owner:Mapped[str]=mapped_column(String(100))
    created_at:Mapped[str]=mapped_column(String(64),default=now)
    # Recovery metadata. Defaults keep archives created before this schema readable.
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    lease_token:Mapped[str]=mapped_column(String(64),default="")
    lease_owner:Mapped[str]=mapped_column(String(120),default="")
    lease_expires_at:Mapped[float]=mapped_column(Double(asdecimal=False),default=0)
    claimed_at:Mapped[str]=mapped_column(String(64),default="")
    artifact_written_at:Mapped[str]=mapped_column(String(64),default="")
    artifact_key:Mapped[str]=mapped_column(String(200),default="")
    result_hash:Mapped[str]=mapped_column(String(64),default="")
    finished_at:Mapped[str]=mapped_column(String(64),default="")
    recovery_count:Mapped[int]=mapped_column(Integer,default=0)
    recovery_reason:Mapped[str]=mapped_column(String(500),default="")
    approved_result_hash:Mapped[str]=mapped_column(String(64),default="")
    approved_at:Mapped[str]=mapped_column(String(64),default="")
