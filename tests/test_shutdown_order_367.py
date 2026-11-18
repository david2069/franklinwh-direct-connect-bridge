"""#367: at shutdown the scheduler is stopped AND awaited before held forces are released,
so a tick already running can't arm a force after the release read the held hosts."""
import asyncio

from franklinwh_direct_connect_bridge import scheduler_worker


def test_a_force_armed_by_the_last_tick_is_released():
    held, released = [], []

    async def tick_in_flight(stop):
        await stop.wait()
        await asyncio.sleep(0.05)          # the tick finishes after stop was asked …
        held.append("10.0.0.1")           # … and arms a force

    async def main():
        stop = asyncio.Event()
        task = asyncio.create_task(tick_in_flight(stop))
        await asyncio.sleep(0)
        await scheduler_worker.stop_then_release(
            stop, task, release=lambda why: released.extend(held))

    asyncio.run(main())
    assert released == ["10.0.0.1"]


def test_a_scheduler_that_won_t_stop_still_gets_the_release():
    released = []

    async def stuck(stop):
        await asyncio.sleep(60)

    async def main():
        stop = asyncio.Event()
        task = asyncio.create_task(stuck(stop))
        await scheduler_worker.stop_then_release(
            stop, task, timeout=0.05, release=lambda why: released.append(why))

    asyncio.run(main())
    assert released == ["shutdown"]
