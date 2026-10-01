"""Stage TELECOM: numbering / telecom intelligence from configured phone providers."""

from __future__ import annotations

import asyncio

from collectors.base import BaseCollector, CollectorContext
from core.logging import get_logger
from core.models import Stage, StageResult, StageStatus

log = get_logger("collectors.telecom")


class TelecomCollector(BaseCollector):
    name = "telecom"
    stage = Stage.TELECOM

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_telecom

    async def run(self, ctx: CollectorContext) -> StageResult:
        providers = ctx.registry.phone_providers()
        result = StageResult(stage=self.stage)
        if not providers:
            result.status = StageStatus.SKIPPED
            result.message = "no phone intelligence provider available"
            return result

        async def _one(p):  # type: ignore[no-untyped-def]
            try:
                return await p.lookup(ctx.phone)
            except Exception as exc:  # defensive: providers should already swallow errors
                log.warning("phone provider failed", provider=p.name, error=f"{type(exc).__name__}: {exc}")
                result.errors.append(f"{p.name}: {type(exc).__name__}")
                return []

        outputs = await asyncio.gather(*[_one(p) for p in providers])
        total = 0
        for p, records in zip(providers, outputs):
            for rec in records:
                if not rec.note and rec.field.lower() in ("carrier", "original_carrier", "carrier_name", "location",
                                                          "region", "phone_region"):
                    rec.note = ("Carrier/region information describes numbering-plan allocation or provider data; "
                                "it does not identify a person and may be outdated because of number portability.")
                ctx.sink.telecom.append(rec)
                total += 1
            if p.errors:
                result.errors.extend(f"{p.name}: {e}" for e in p.errors[-3:])
        result.counts = {"providers": len(providers), "records": total}
        result.message = f"{total} telecom records from {len(providers)} provider(s)"
        return result
