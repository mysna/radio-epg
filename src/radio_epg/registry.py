"""설정에 선언된 adapter factory를 안전하게 연결한다."""

from collections.abc import Callable, Iterable

from radio_epg.adapters.base import ScheduleAdapter
from radio_epg.config import SourceConfig

AdapterFactory = Callable[[SourceConfig], ScheduleAdapter]


class AdapterRegistry:
    """adapter 이름을 생성 함수에 매핑한다."""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, name: str, factory: AdapterFactory) -> None:
        """중복 이름을 허용하지 않고 factory를 등록한다."""
        if name in self._factories:
            raise ValueError(f"adapter {name!r} is already registered")
        self._factories[name] = factory

    def build(
        self,
        sources: Iterable[SourceConfig],
        *,
        source_ids: set[str] | None = None,
    ) -> tuple[ScheduleAdapter, ...]:
        """활성화되고 선택된 source의 adapter만 설정 순서대로 만든다."""
        adapters: list[ScheduleAdapter] = []
        for source in sources:
            selected = source_ids is None or source.source_id in source_ids
            if not source.enabled or not selected:
                continue
            factory = self._factories.get(source.adapter)
            if factory is None:
                raise LookupError(f"adapter {source.adapter!r} is not registered")
            adapters.append(factory(source))
        return tuple(adapters)


def default_registry() -> AdapterRegistry:
    """프로젝트에 포함된 adapter registry를 만든다."""
    from radio_epg.adapters.afn import AfnAdapter
    from radio_epg.adapters.cbs import CbsAdapter
    from radio_epg.adapters.community import CommunityAdapter
    from radio_epg.adapters.ebs import EbsAdapter
    from radio_epg.adapters.febc import FebcAdapter
    from radio_epg.adapters.independent import IndependentAdapter
    from radio_epg.adapters.kbs import KbsAdapter
    from radio_epg.adapters.mbc import MbcAdapter
    from radio_epg.adapters.regional_mbc import RegionalMbcAdapter
    from radio_epg.adapters.religious import ReligiousAdapter
    from radio_epg.adapters.sbs import SbsAdapter
    from radio_epg.adapters.sbs_affiliates import SbsAffiliatesAdapter
    from radio_epg.adapters.tbn import TbnAdapter

    registry = AdapterRegistry()

    def build_kbs(source: SourceConfig) -> ScheduleAdapter:
        return KbsAdapter(source)

    registry.register("kbs", build_kbs)
    registry.register("mbc", MbcAdapter)
    registry.register("sbs", SbsAdapter)
    registry.register("ebs", EbsAdapter)
    registry.register("cbs", CbsAdapter)
    registry.register("tbn", TbnAdapter)
    registry.register("regional_mbc", RegionalMbcAdapter)
    registry.register("sbs_affiliates", SbsAffiliatesAdapter)
    registry.register("febc", FebcAdapter)
    registry.register("religious", ReligiousAdapter)
    registry.register("independent", IndependentAdapter)
    registry.register("community", CommunityAdapter)
    registry.register("afn", AfnAdapter)
    return registry
