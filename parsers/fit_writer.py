from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from garmin_fit_sdk import Encoder, Profile

from models.dive_plan import DiveProfilePlan
from parsers.plan_embed import fit_plan_messages
from parsers.uddf_writer import log_start_time
from utils.dive_computers import dive_computer
from utils.dive_plan_engine import SimulatedSample

FIT_EPOCH = datetime(1989, 12, 31)
# Tank pod serials the written file reports its tanks under, in
# DiveProfilePlan.tank_specs() order - FIT only knows a tank by its
# transmitter's serial.
TANK_SENSOR_BASE = 100001


# file_creator.software_version of a UWMedia-written FIT (the marker proper is
# the developer_data_id's application_id - see plan_embed.FIT_APPLICATION_ID).
PLAN_SOFTWARE_VERSION = 800


def _mesg_num(name: str) -> int:
    # Profile["messages"] is keyed by the int number; its own "num" is a string.
    return next(num for num, m in Profile["messages"].items() if m["name"] == name)


def _fit_local(local: datetime) -> int:
    """A naive local time as a FIT local_date_time (seconds since the FIT epoch)."""
    return int((local - FIT_EPOCH).total_seconds())


def write_fit(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    file_path: Path,
    start_time: Optional[datetime] = None,
) -> None:
    """Writes `samples` (from utils.dive_plan_engine.simulate) as a Garmin
    Descent style FIT activity - message set and field use matched against
    real Mk3i exports (test_data/logs/fit/*.fit) closely enough that
    parsers/garmin.py's GarminParser reads it back (see
    tests/test_log_writers.py): file_id/device_info naming the computer,
    dive_settings, one dive_gas per gas, a record per sample, a
    tank_update per tank per sample (every tank a tank pod, named by its
    tank ref in device_info's descriptor), then summary, session and
    activity messages carrying the start time in both UTC and local time.

    FIT is Garmin's own format, so plan.computer must be a Garmin model.
    """
    if not samples:
        raise ValueError("No samples to write - run utils.dive_plan_engine.simulate() first")
    computer = dive_computer(plan.computer)
    if not computer.is_garmin:
        raise ValueError(f"FIT files come from Garmin dive computers - {computer.label} doesn't write them")
    start_local = log_start_time(plan, start_time)
    start_utc = start_local.astimezone().astimezone(timezone.utc)
    serial = int(plan.computer_serial) if plan.computer_serial.isdigit() else 0
    duration = samples[-1].time_sec
    end_utc = datetime.fromtimestamp(start_utc.timestamp() + duration, tz=timezone.utc)
    tanks = plan.tank_specs()
    sensor_of = {t.ref: TANK_SENSOR_BASE + i for i, t in enumerate(tanks)}
    gas_index = {g.id: i for i, g in enumerate(plan.gases)}

    encoder = Encoder()

    def write(name: str, **fields) -> None:
        encoder.write_mesg({"mesg_num": _mesg_num(name), **fields})

    def at(time_sec: int) -> datetime:
        return datetime.fromtimestamp(start_utc.timestamp() + time_sec, tz=timezone.utc)

    write("file_id", type="activity", manufacturer="garmin", product=computer.fit_product,
          serial_number=serial, time_created=start_utc)
    # UWMedia's mark and the plan itself, as developer data on the
    # file_creator message, so the builder can open this file again
    # (parsers/plan_embed.py). The developer_data_id / field_description
    # messages have to precede the message that carries the fields.
    plan_messages, plan_fields = fit_plan_messages(encoder, plan, _mesg_num)
    for mesg in plan_messages:
        encoder.write_mesg(mesg)
    write("file_creator", software_version=PLAN_SOFTWARE_VERSION, developer_fields=plan_fields)
    write("device_info", timestamp=start_utc, device_index="creator", manufacturer="garmin",
          product=computer.fit_product, serial_number=serial, source_type="local")
    for i, tank in enumerate(tanks):
        write("device_info", timestamp=start_utc, device_index=i + 1, manufacturer="garmin",
              serial_number=sensor_of[tank.ref], descriptor=tank.ref, source_type="antplus")

    write("dive_settings", timestamp=start_utc, message_index=0, model="zhl_16c",
          gf_low=int(plan.gf_low), gf_high=int(plan.gf_high), water_type="salt",
          po2_warn=plan.max_po2_bottom, po2_critical=plan.max_po2_deco, po2_deco=plan.max_po2_deco,
          safety_stop_enabled=1, safety_stop_time=180,
          ccr_low_setpoint_switch_mode="automatic", ccr_low_setpoint=plan.ccr_low_setpoint,
          ccr_low_setpoint_depth=plan.ccr_setpoint_switch_depth_m,
          ccr_high_setpoint_switch_mode="automatic", ccr_high_setpoint=plan.ccr_high_setpoint,
          ccr_high_setpoint_depth=plan.ccr_setpoint_switch_depth_m)
    for gas in plan.gases:
        write("dive_gas", message_index=gas_index[gas.id], helium_content=round(gas.he_percent),
              oxygen_content=round(gas.o2_percent), status="enabled",
              mode="closed_circuit_diluent" if plan.on_loop(gas) else "open_circuit")

    write("event", timestamp=start_utc, event="timer", event_type="start", event_group=0)

    last_gas = None
    for i, s in enumerate(samples):
        ts = at(s.time_sec)
        if s.gas_id != last_gas:
            if last_gas is not None:
                write("event", timestamp=ts, event="dive_gas_switched", event_type="marker",
                      data=gas_index[s.gas_id])
            last_gas = s.gas_id
        previous = samples[i - 1] if i > 0 else s
        dt = s.time_sec - previous.time_sec
        # FIT logs it in m/s, positive = getting shallower.
        ascent_rate = (previous.depth_m - s.depth_m) / dt if dt > 0 else 0.0
        write("record", timestamp=ts, depth=round(s.depth_m, 3), temperature=round(plan.water_temp_c),
              next_stop_depth=round(s.stop_depth_m, 1) if s.ceiling_m > 0 else 0.0,
              next_stop_time=s.stop_duration_sec if s.ceiling_m > 0 else 0,
              time_to_surface=s.tts_sec, ndl_time=s.ndl_sec if s.ndl_sec is not None else 0,
              cns_load=int(s.cns_pct), po2=round(s.po2, 2), ascent_rate=round(ascent_rate, 3))
        for tank in tanks:
            if tank.ref in s.tank_pressures:
                write("tank_update", timestamp=ts, sensor=sensor_of[tank.ref],
                      pressure=s.tank_pressures[tank.ref])

    write("event", timestamp=end_utc, event="timer", event_type="stop_all", event_group=0)

    end_pressures = samples[-1].tank_pressures
    for tank in tanks:
        end = end_pressures.get(tank.ref, tank.start_pressure_bar)
        write("tank_summary", timestamp=end_utc, sensor=sensor_of[tank.ref],
              start_pressure=tank.start_pressure_bar, end_pressure=end,
              volume_used=max(0.0, (tank.start_pressure_bar - end) * tank.size_l))

    depths = [s.depth_m for s in samples]
    if plan.is_ccr:
        sub_sport = "ccr_diving"
    elif len(plan.gases) > 1:
        sub_sport = "multi_gas_diving"
    else:
        sub_sport = "single_gas_diving"
    write("dive_summary", timestamp=end_utc, reference_mesg="session", reference_index=0,
          avg_depth=round(sum(depths) / len(depths), 3), max_depth=round(max(depths), 3),
          start_cns=0, end_cns=int(samples[-1].cns_pct), dive_number=1, bottom_time=float(duration))
    write("lap", message_index=0, timestamp=end_utc, event="lap", event_type="stop",
          start_time=start_utc, total_elapsed_time=float(duration), total_timer_time=float(duration),
          sport="diving", sub_sport=sub_sport)
    # Real Descent files stamp session and activity with the dive's start,
    # which is what GarminParser reads the start from.
    write("session", message_index=0, timestamp=start_utc, event="session", event_type="stop",
          start_time=start_utc, total_elapsed_time=float(duration), total_timer_time=float(duration),
          sport="diving", sub_sport=sub_sport, first_lap_index=0, num_laps=1, trigger="activity_end",
          avg_temperature=round(plan.water_temp_c), max_temperature=round(plan.water_temp_c))
    write("activity", timestamp=start_utc, total_timer_time=float(duration), num_sessions=1,
          type="manual", event="activity", event_type="stop", local_timestamp=_fit_local(start_local))

    Path(file_path).write_bytes(encoder.close())
