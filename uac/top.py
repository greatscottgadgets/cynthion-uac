#!/usr/bin/env python3

import logging

from amaranth            import *
from amaranth.lib        import wiring
from amaranth.lib.memory import Memory

from luna                import top_level_cli

from .uac2               import USBAudioClass2Device
from .                   import dsp


class Top(Elaboratable):
    def __init__(self):
        self.clock_frequencies   = {
            "fast": 240,
            "sync": 120,
            "usb":  60,
        }

        self.sample_rate         = 48e3
        self.bit_depth           = 24
        self.channels            = 2

        self.lut_length          = 256


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains and resets.
        m.submodules.car = platform.clock_domain_generator(clock_frequencies=self.clock_frequencies)

        # Instantiate our UAC 2.0 Device.
        m.submodules.uac2 = uac2 = USBAudioClass2Device(
            sample_rate = self.sample_rate,
            bit_depth   = self.bit_depth,
            channels    = self.channels,
            bus         = platform.request("target_phy"),
        )

        # Instantiate our sin LUT.
        gain  = 1.0
        #gain = 0.794328 # -2dB
        #gain = 0.501187 # -6dB
        m.submodules.lut = lut = Memory(
            shape  = signed(self.bit_depth),
            depth  = self.lut_length,
            init   = dsp.sinusoid_lut(self.bit_depth, self.lut_length, gain=gain, signed=True),
        )

        # Instantiate our NCOs.
        m.submodules.nco0 = nco0 = DomainRenamer({"sync": "usb"})(dsp.NCO(lut))
        m.submodules.nco1 = nco1 = DomainRenamer({"sync": "usb"})(dsp.NCO(lut))
        m.d.comb += [
            nco0.phi_delta.eq(int(1000.  * nco0.phi_tau / self.sample_rate)),
            nco1.phi_delta.eq(int(10000. * nco1.phi_tau / self.sample_rate)),
        ]

        # Connect our NCO's to the UAC 2.0 device's inputs
        wiring.connect(m, nco0.output, uac2.inputs[0])
        wiring.connect(m, nco1.output, uac2.inputs[1])

        # Instantiate our VU meter.
        m.submodules.vu = vu = DomainRenamer({"sync": "usb"})(
            dsp.VU(
                sample_rate     = self.sample_rate,
                bit_depth       = self.bit_depth,
                clock_frequency = self.clock_frequencies["usb"]  * 1e6,
                segments        = 6,
            )
        )

        # Connect the UAC device's outputs to our VU meter.
        wiring.connect(m, uac2.outputs[0], vu.input)

        # Connect the VU meter's led output to Cynthion USER LEDs.
        leds: Signal(6) = Cat(platform.request("led", n).o for n in range(0, 6))
        m.d.comb += leds.eq(vu.leds)

        # Instantiate our ∆Σ DAC.
        m.submodules.dac = dac = DomainRenamer({"sync": "usb"})(
            dsp.DAC(
                sample_rate     = self.sample_rate,
                bit_depth       = self.bit_depth,
                channels        = self.channels,
                clock_frequency = self.clock_frequencies["usb"]  * 1e6,
                signed          = True,
            )
        )

        # Connect our UAC 2.0 device's outputs to our ∆Σ DAC's inputs
        wiring.connect(m, uac2.outputs[0], dac.inputs[0])
        wiring.connect(m, uac2.outputs[1], dac.inputs[1])

        # Connect our ∆Σ DAC outputs to our USER PMOD pins.
        pmod1 = platform.request("user_pmod", 1)
        m.d.comb += [
            pmod1.oe.eq(1),
            pmod1.o[0].eq(dac.outputs[0]),
            pmod1.o[1].eq(dac.outputs[1]),
        ]

        # debug
        debug = platform.request("user_pmod", 0)
        m.d.comb += debug.oe.eq(1)
        m.d.comb += [
            #debug.o[0] .eq(leds),
        ]

        return m


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    top_level_cli(Top)
