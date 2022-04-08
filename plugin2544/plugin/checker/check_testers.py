
import asyncio
from typing import List, TYPE_CHECKING


from ...utils.errors import ConfigError
from xoa_driver import testers

if TYPE_CHECKING:
    from valhalla_core.test_suit_plugin.plugins.plugin2544.model import TestConfiguration

async def check_tester_sync_start(
    tester: "testers.L23Tester", use_sync_start: bool
) -> None:
    if not use_sync_start:
        return
    cap = await tester.capabilities.get()
    if not bool(cap.can_sync_traffic_start):
        raise ConfigError(f"Tester does not support port staggering")


async def check_testers(
    testers: List["testers.L23Tester"], test_conf: "TestConfiguration"
):
    await asyncio.gather(
        *[
            check_tester_sync_start(tester, test_conf.use_port_sync_start)
            for tester in testers
        ]
    )