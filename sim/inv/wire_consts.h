/* Constants of the wire invariants I3 to I6b. The values and the line of docs/lockers/hardware-safety.md each comes from
 * are in policy/sim_constants.toml (gate-owned); gate/tests/test_sim_wire_data.py keeps this file equal to it. */
#ifndef SIM_INV_WIRE_CONSTS_H
#define SIM_INV_WIRE_CONSTS_H

enum {
    WIRE_PULSE_CAP_UNITS = 8,
    WIRE_PULSE_UNIT_MS = 100,
    WIRE_FLASH_EARLY_OFF_MS = 30,
    WIRE_GAP_MS = 300,
    WIRE_WATCHDOG_MARGIN_MS = 150,
    WIRE_WATCHDOG_CAP_MS = 900,
    WIRE_BURN_MS = 1000,
    WIRE_MAX_ENERGISED_COILS = 2,
    WIRE_VERIFY_SLACK_MS = 150,
    WIRE_COILS = 30,
    WIRE_SLAVE_ID = 1,
    WIRE_FLASH_BASE = 0x0200,
    WIRE_ALL_OFF_ADDR = 0x00FF,
    WIRE_VERSION_REG = 0x8000,
    WIRE_CONFIG_REG = 0x4000,
    WIRE_ON_VALUE = 0xFF00,
    WIRE_TOGGLE_VALUE = 0x5500,
};

#endif
