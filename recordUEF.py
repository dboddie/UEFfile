#!/usr/bin/env python

"""
recordUEF.py - Convert audio files into UEF files.

Copyright (C) 2015 David Boddie <david@boddie.org.uk>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import struct, sys

def find_option(args, label, number = 0):

    """Matches an option in a list of command line arguments, returning a
    single boolean value for options without arguments and a tuple for options
    with arguments.
    
    For options with arguments, the tuple contains a boolean value and a list
    of arguments found unless only one argument is expected, in which case the
    value itself is included in the tuple instead of a list.
    
    If the boolean value is True, the option was found. If it is False then
    either it was not found or the required number of arguments was not found.
    """
    
    try:
        i = args.index(label)
    except ValueError:
        if number == 0:
            return False
        else:
            return False, None
    
    values = args[i + 1:i + number + 1]
    args[:] = args[:i] + args[i + number + 1:]
    
    if number == 0:
        return True
    
    if len(values) < number:
        return False, values
    
    if number == 1:
        values = values[0]
    
    return True, values


class Reader:

    def __init__(self, format, step, midpoint):
    
        self.format = format
        self.step = step
        self.midpoint = midpoint
        
        self.T = 0
    
    def read_samples(self, audio_f):
    
        sign = None
        t = 0
        state = "waiting"
        current = None
        cycles = 0
        data = []
        bits = 0
        shift = 0
        
        while True:
        
            sample = audio_f.read(self.step)
            if not sample:
                raise StopIteration
            
            values = struct.unpack(format, sample)
            value = values[0] - self.midpoint
            
            if value > 0:
                if sign == "-":
                    f = 1.0/t
                    if 2000 <= f <= 2800:
                        new_current = "high"
                    elif 1000 <= f <= 1400:
                        new_current = "low"
                    else:
                        new_current = None
                    
                    if current != new_current:
                        cycles = 0
                    else:
                        cycles += 1
                    
                    current = new_current
                    print state, current, cycles
                    
                    if current == "high" and cycles == 2:
                        if state == "data":
                            bits = (bits >> 1) | 0x80
                            shift += 1
                        elif state == "waiting":
                            state = "ready"
                        elif state == "after":
                            state = "ready"
                            yield bits
                        
                        cycles = 0
                    
                    elif current == "low" and cycles == 1:
                        if state == "data":
                            bits = bits >> 1
                            shift += 1
                        elif state == "ready":
                            state = "data"
                            bits = 0
                        
                        cycles = 0
                    
                    if shift == 8:
                        state = "after"
                        shift = 0
                    
                    t = 0
                
                else:
                    t += dt
                
                sign = "+"
            
            elif value < 0:
                sign = "-"
                t += dt
            else:
                t += dt
            
            self.T += dt


if __name__ == "__main__":

    program_name, args = sys.argv[0], sys.argv[1:]
    
    r, sample_rate = find_option(args, "--rate", 1)
    mono = find_option(args, "--mono", 0)
    unsigned = find_option(args, "--unsigned", 0)
    s, sample_size = find_option(args, "--size", 1)
    
    if len(args) != 2 or not s or not r:
        sys.stderr.write("Usage: %s [--rate <sample rate in Hz>] [--mono] [--unsigned] [--size <sample size in bits>] <audio file> <UEF file>\n" % program_name)
        sys.exit(1)
    
    audio_file = args[0]
    uef_file = args[1]
    
    if audio_file == "-":
        audio_f = sys.stdin
    else:
        audio_f = open(audio_file, "rb")
    
    dt = 1.0/float(sample_rate)
    one_dt = 0.5/2400
    zero_dt = 0.5/1200
    
    try:
        sample_size = int(sample_size)
        if sample_size not in (8, 16):
            raise ValueError
    except ValueError:
        sys.stderr.write("Invalid sample size: %s\n" % sample_size)
        sys.exit(1)
    
    step = int(sample_size/8)
    
    if sample_size == 8:
        format = "b"
    else:
        format = "h"
    
    if not mono:
        step = step * 2
        format = format * 2
    
    if unsigned:
        format = format.upper()
        midpoint = 1 << (sample_size - 1)
    else:
        midpoint = 0
    
    format = "<" + format
    reader = Reader(format, step, midpoint)
    
    last_T = 0
    
    for byte in reader.read_samples(audio_f):
    
        print hex(byte),
        if int(reader.T) > last_T:
            last_T = int(reader.T)
            print
            print ">", last_T
    
    sys.exit()
