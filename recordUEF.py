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
import UEFfile

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


class Block(UEFfile.UEFfile):

    def __init__(self, gen):
    
        self.name = ""
        header = ""
        
        while len(self.name) < 10:
            byte = gen.next()
            header += chr(byte)
            if byte != 0:
                self.name += chr(byte)
            else:
                break
        
        if len(self.name) == 10:
            header += chr(gen.next())
        
        self.load_addr = sum(map(lambda x: gen.next() << x, range(0, 32, 8)))
        header += struct.pack("<I", self.load_addr)
        self.exec_addr = sum(map(lambda x: gen.next() << x, range(0, 32, 8)))
        header += struct.pack("<I", self.exec_addr)
        self.number = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        header += struct.pack("<H", self.number)
        self.length = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        header += struct.pack("<H", self.length)
        
        print self.name, hex(self.load_addr), hex(self.exec_addr), self.number, self.length
        
        if self.length > 256:
            raise ValueError, "Invalid block length."
        
        self.flag = gen.next()
        header += chr(self.flag)
        self.next = sum(map(lambda x: gen.next() << x, range(0, 32, 8)))
        header += struct.pack("<I", self.next)
        
        self.header_crc = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        
        print self.flag, self.next, hex(self.header_crc)
        
        if self.crc(header) != self.header_crc:
            print "Invalid block header.", self.crc(header), self.header_crc
            raise ValueError, "Invalid block header."
        
        self.block = "".join(map(lambda x: chr(gen.next()), range(self.length)))
        self.block_crc = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        
        print repr(self.block), len(self.block)
        
        if self.crc(self.block) != self.block_crc:
            print "Invalid block.", hex(self.crc(self.block)), hex(self.block_crc)
            raise ValueError, "Invalid block."
        
        print repr(self.block)
        print hex(self.block_crc)


class Reader:

    def __init__(self, format, step, dt):
    
        self.format = format
        self.step = step
        self.dt = dt
        
        samples_per_second = 1.0/dt
        self.weight = samples_per_second/100.0
        self.mean = 0
        self.previous = 0
        
        self.T = 0
    
    def start_at(self, start_time):
    
        self.start_time = start_time
    
    def read_byte(self, audio_f):
    
        sign = None
        t = 0
        state = "waiting"
        current = None
        cycles = 0
        data = []
        bits = 0
        shift = 0
        crossing = 0
        
        while True:
        
            sample = audio_f.read(self.step)
            if not sample:
                raise StopIteration
            
            values = struct.unpack(format, sample)
            value = values[0]
            
            if self.T < self.start_time:
                self.T += self.dt
                continue
            
            self.mean = (value/self.weight) + self.mean * (1 - 1/self.weight)
            
            #print " ", self.T, audio_f.tell(), values
            value -= self.mean
            pv = self.previous
            self.previous = value
            
            if t > 0 and (pv * value) < 0:
            
                tc = (value * self.dt)/(value - pv)
                f = 1.0/(t - tc)
                
                crossing = 1 - crossing
                
                #print " ", self.T, f, crossing, state, current
                
                if crossing == 0:
                
                    if 2000 <= f <= 2800:
                        new_current = "high"
                    elif 1500 <= f <= 1700:
                        # Out of sync by half a wavelength.
                        new_current = None
                        crossing = 1
                    elif 1100 <= f <= 1300:
                        new_current = "low"
                    else:
                        new_current = None
                    
                    #print ">", self.T, f, new_current
                    # Only handle frequencies we recognise.
                    if new_current:

                        #print ">", self.T, self.T - tc, f
                        current = new_current

                        if current == "high":
                            if state == "waiting":
                                state = "ready"
                                #print self.T, state
                            elif state == "after":
                                state = "ready"
                                #print self.T, state
                                yield bits
                            elif state == "data":
                                cycles += 1
                                if cycles == 2:
                                    bits = (bits >> 1) | 0x80
                                    shift += 1
                                    cycles = 0
                                    print "1", self.T, hex(bits)

                        elif current == "low":
                            if state == "data":
                                bits = bits >> 1
                                shift += 1
                                print "0", self.T, hex(bits)

                            elif state == "ready":
                                state = "data"
                                #print self.T, state
                                bits = 0
                                shift = 0

                            cycles = 0

                        if shift == 8:
                            print hex(bits)
                            state = "after"
                            shift = 0

                        #print ">", self.T, f, state, hex(bits), shift
                    
                    if current or f < 1100:
                        t = tc + self.dt
                    else:
                        t += self.dt
                    
                else:
                    t += self.dt
            else:
                t += self.dt
            
            self.T += self.dt
    
    def read_block(self, audio_f):
    
        gen = self.read_byte(audio_f)
        while True:
        
            byte = gen.next()
            
            if byte == 0x2a:
                try:
                    print ">", self.T
                    yield Block(gen)
                except ValueError:
                    raise


if __name__ == "__main__":

    program_name, args = sys.argv[0], sys.argv[1:]
    
    r, sample_rate = find_option(args, "--rate", 1)
    mono = find_option(args, "--mono", 0)
    unsigned = find_option(args, "--unsigned", 0)
    s, sample_size = find_option(args, "--size", 1)
    start, start_time = find_option(args, "--start", 1)
    
    if len(args) != 2 or not s or not r:
        sys.stderr.write("Usage: %s [--rate <sample rate in Hz>] [--mono] [--unsigned] [--size <sample size in bits>] [--start <time in seconds>] <audio file> <UEF file>\n" % program_name)
        sys.exit(1)
    
    audio_file = args[0]
    uef_file = args[1]
    
    if audio_file == "-":
        audio_f = sys.stdin
    else:
        audio_f = open(audio_file, "rb")
    
    dt = 1.0/float(sample_rate)
    
    try:
        sample_size = int(sample_size)
        if sample_size not in (8, 16):
            raise ValueError
    except ValueError:
        sys.stderr.write("Invalid sample size: %s\n" % sample_size)
        sys.exit(1)
    
    if not start:
        start_time = 0.0
    
    step = int(sample_size/8)
    
    if sample_size == 8:
        format = "b"
    else:
        format = "h"
    
    if not mono:
        step = step * 2
        format = format * 2
    
    format = "<" + format
    reader = Reader(format, step, dt)
    reader.start_at(float(start_time))
    
    last_T = 0
    data = []
    
    if True:
        for byte in reader.read_byte(audio_f):
        
            data.append(byte)
            #print reader.T, hex(byte)
            if int(reader.T) > last_T:
                last_T = int(reader.T)
                #sys.stdout.write("\r%02i:%02i" % (last_T/60, last_T % 60))
                #sys.stdout.flush()
                #print ">", last_T
    else:
        for block in reader.read_block(audio_f):
            print block.name, hex(block.load_addr), hex(block.exec_addr), block.number, block.length
    
    #sys.exit()
