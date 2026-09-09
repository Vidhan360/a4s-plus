"""Command-dashboard aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults import DATA_DISCLAIMER
from app.models.enums import RiskCategory
from app.repositories import alerts as alert_repo
from app.repositories import drones as drone_repo
from app.repositories import personnel as personnel_repo
from app.repositories import system as system_repo
from app.services.prediction_service import get_prediction_service
from app.services.twin_service import DigitalTwinService

DISCLAIMER = {
    "data_mode": "SOFTWARE PROTOTYPE / SIMULATED DATA",
    "validation_status": "NOT CLINICALLY VALIDATED",
    "notice": DATA_DISCLAIMER,
}


class DashboardService:
    def __init__(self, twin_service: DigitalTwinService | None = None) -> None:
        self.twins = twin_service or DigitalTwinService()

    async def snapshot(self, session: AsyncSession) -> dict[str, Any]:
        from app.simulation.engine import simulation_engine

        person_counts = await personnel_repo.counts(session)
        twins = await personnel_repo.twin_rows(session)
        distribution = {c.value: 0 for c in RiskCategory}
        scored = [t for t in twins if t.risk_score is not None]
        for twin in twins:
            if twin.risk_category in distribution:
                distribution[twin.risk_category] += 1
        average = (
            round(sum(float(t.risk_score or 0.0) for t in scored) / len(scored), 2)
            if scored
            else 0.0
        )
        highest = None
        if scored:
            top = max(scored, key=lambda t: float(t.risk_score or 0.0))
            highest = self.twins.summary_row(top)

        open_alerts = await alert_repo.open_count(session)
        by_severity = await alert_repo.counts_by_severity(session)
        critical = await alert_repo.critical_open(session, limit=8)

        watchlist = [
            self.twins.summary_row(t)
            for t in sorted(scored, key=lambda t: float(t.risk_score or 0.0), reverse=True)[:6]
        ]

        drone_status = await drone_repo.status_counts(session)
        drone_comms = await drone_repo.comms_counts(session)
        drone_rows = await drone_repo.list_drones(session)
        drones = {
            "total": len(drone_rows),
            "by_status": drone_status,
            "by_comms": drone_comms,
            "jammed": sum(1 for d in drone_rows if d.under_jamming),
            "spoofed": sum(1 for d in drone_rows if d.under_spoofing),
            "autonomous": sum(1 for d in drone_rows if d.autonomous_mode),
            "mean_battery_pct": (
                round(sum(d.battery_pct for d in drone_rows) / len(drone_rows), 1)
                if drone_rows
                else 0.0
            ),
            "is_simulated": True,
        }

        posture = await system_repo.security_posture(session)
        sim_status = simulation_engine.status_payload()
        environment = None
        if simulation_engine.tick_count > 0:
            environment = simulation_engine._env.step(simulation_engine.sim_clock_seconds).as_dict()

        return {
            "generated_at": datetime.now(timezone.utc),
            "personnel_total": person_counts["total"],
            "personnel_active": person_counts["active"],
            "risk_distribution": distribution,
            "average_risk": average,
            "highest_risk": highest,
            "open_alerts": open_alerts,
            "alerts_by_severity": by_severity,
            "critical_alerts": critical,
            "watchlist": watchlist,
            "drones": drones,
            "security": posture,
            "simulation": sim_status,
            "environment": environment,
            "prediction_models": get_prediction_service().describe_all(),
            "disclaimer": DISCLAIMER,
        }


dashboard_service = DashboardService()
