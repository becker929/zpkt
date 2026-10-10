"""A copy of the BSD fixture set with devices planted on its audio track, shaped like Live 12's.

Track "1-Audio" gets a Utility (StereoGain), a Decapitator (VST, two configured parameters) and an
EQ Eight with one band, with values taken from HW002's rumble chain, whose LOM values are known
(tests/test_knobs.py). Pointee ids 22100-22125 sit above the fixture's own (max 22030), and
NextPointeeId is raised to 22200, as Live keeps it.
"""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

from hands import als

FIXTURE = Path(__file__).parent / "fixtures" / "L12-automation.als"
TRACK = "1-Audio"


def _switch(tag: str, value: str, at: int) -> str:
    return (f'<{tag}><LomId Value="0" /><Manual Value="{value}" />'
            f'<AutomationTarget Id="{at}"><LockEnvelope Value="0" /></AutomationTarget>'
            f'<MidiCCOnOffThresholds><Min Value="64" /><Max Value="127" /></MidiCCOnOffThresholds></{tag}>')


def _number(tag: str, value: str, lo: str, hi: str, at: int, mt: int | None = None) -> str:
    mod = f'<ModulationTarget Id="{mt}"><LockEnvelope Value="0" /></ModulationTarget>' if mt else ""
    return (f'<{tag}><LomId Value="0" /><Manual Value="{value}" />'
            f'<MidiControllerRange><Min Value="{lo}" /><Max Value="{hi}" /></MidiControllerRange>'
            f'<AutomationTarget Id="{at}"><LockEnvelope Value="0" /></AutomationTarget>{mod}</{tag}>')


def _plugin_param(index: int, name: str, value: str, at: int) -> str:
    return (f'<PluginFloatParameter Id="{index}"><ParameterName Value="{name}" /><ParameterId Value="{index}" />'
            + _number("ParameterValue", value, "0", "1", at, at + 1) + "</PluginFloatParameter>")


UTILITY = ('<StereoGain Id="0">' + _switch("On", "true", 22100) + '<UserName Value="" /><Pointee Id="22101" />'
           + _number("ChannelMode", "1", "0", "3", 22102)
           + _number("StereoWidth", "0.8770471215", "0", "4", 22103, 22104)
           + _switch("BassMono", "false", 22105)
           + _number("BassMonoFrequency", "120", "50", "500", 22106, 22107)
           + _number("Gain", "0.4084238708", "0", "56.2341309", 22108, 22109)
           + "</StereoGain>")
DECAPITATOR = ('<PluginDevice Id="1">' + _switch("On", "true", 22110) + '<UserName Value="" /><Pointee Id="22111" />'
               '<PluginDesc><VstPluginInfo Id="0"><PlugName Value="Decapitator" /></VstPluginInfo></PluginDesc>'
               "<ParameterList>" + _plugin_param(0, "Drive", "0.27", 22112) + _plugin_param(1, "Mix", "1", 22114)
               + "</ParameterList></PluginDevice>")
EQ8 = ('<Eq8 Id="2">' + _switch("On", "true", 22116) + '<UserName Value="" /><Pointee Id="22117" />'
       "<Bands.0><ParameterA>" + _switch("IsOn", "true", 22118)
       + _number("Freq", "30.9539299", "10", "22000", 22119, 22120)
       + _number("Gain", "-14.2561979", "-15", "15", 22121, 22122)
       + _number("Q", "2.29257298", "0.1000000015", "18", 22123, 22124)
       + "</ParameterA></Bands.0></Eq8>")


def planted_tree() -> ET.ElementTree:
    tree = als.load(FIXTURE)
    track = als.find_track(tree, TRACK)
    chain = track.find("DeviceChain/DeviceChain/Devices")
    for xml in (UTILITY, DECAPITATOR, EQ8):
        chain.append(ET.fromstring(xml))
    tree.getroot().find("LiveSet/NextPointeeId").set("Value", "22200")
    return tree


def planted_set(path: Path) -> Path:
    """Write the planted set to `path` (a .als) and return it."""
    als.save(planted_tree(), path, overwrite=True)
    return path


def xml_text(path: Path) -> str:
    return gzip.open(path).read().decode()
