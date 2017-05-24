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

import math, struct, sys
import UEFfile

version = "0.1"

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


def hms(t):

    s = t % 60.0
    m = (int(t) / 60) % 60
    h = int(t) / 3600
    
    st = ""
    if h > 0:
        st += "%i:" % h
    if h > 0 or m > 0:
        st += "%02i:" % m
    
    i = s - int(s)
    return st + ("%08.5f" % s)


def from_hms(text):

    pieces = text.split(":")
    
    total = 0
    factor = 1
    
    while pieces:
        total += float(pieces.pop()) * factor
        factor *= 60
    
    return total


class Block(UEFfile.UEFfile):

    def __init__(self, t, gen, debug):
    
        self.T = t
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
        
        if debug:
            print >>sys.stderr, repr(self.name), hex(self.load_addr), hex(self.exec_addr), hex(self.number), self.length
        
        if self.length > 256:
            raise ValueError("Invalid block length (%i) at %s." % (
                self.length, hms(self.T)))
        
        self.flags = gen.next()
        header += chr(self.flags)
        self.next = sum(map(lambda x: gen.next() << x, range(0, 32, 8)))
        header += struct.pack("<I", self.next)
        
        self.header = header
        self.header_crc = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        
        if debug:
            print >>sys.stderr, self.flags, self.next, hex(self.header_crc)
        
        if self.crc(header) != self.header_crc:
            raise ValueError("Invalid block header (%x != %x) at %s." % (
                self.crc(header), self.header_crc, hms(self.T)))
        
        self.block = "".join(map(lambda x: chr(gen.next()), range(self.length)))
        self.block_crc = sum(map(lambda x: gen.next() << x, range(0, 16, 8)))
        
        if debug:
            print >>sys.stderr, repr(self.block), len(self.block)
        
        if self.crc(self.block) != self.block_crc:
            raise ValueError("Invalid block (%x != %x) at %s." % (
                self.crc(self.block), self.block_crc, hms(self.T)))
        
        if debug:
            print >>sys.stderr, repr(self.block)
            print >>sys.stderr, hex(self.block_crc)
    
    def data(self):
    
        return "*" + self.header + struct.pack("<H", self.header_crc) + \
                     self.block + struct.pack("<H", self.block_crc)


class Reader:

    def __init__(self, format, step, sample_rate, boost_factor, f1, f2,
                       width_1200, width_2400, zero_count,
                       filter_, adapt_frequency, quiet, debug):
    
        self.format = format
        self.step = step
        self.sample_rate = sample_rate
        self.boost_factor = boost_factor
        self.filter_ = filter_
        self.adapt_frequency = adapt_frequency
        self.quiet = quiet
        self.debug = debug
        
        self.f1 = f1
        self.f2 = f2
        self.width_1200 = width_1200
        self.width_2400 = width_2400
        self.zero_count = self.sample_rate/zero_count
        
        self.dt = 1.0/sample_rate
        self.T = 0
        self.stop_time = None
    
    def start_at(self, start_time):
    
        self.start_time = start_time
        self.T = start_time
    
    def stop_at(self, stop_time):
    
        self.stop_time = stop_time
    
    def V(self, V0, Vapp, R, C, dt):
    
        # The current that flows is due to the potential difference between the
        # applied potential and the potential at the capacitor. The resistor acts
        # to moderate this flow.
        i = (Vapp - V0)/R
        # Change the charge at the capacitor by the new charge transported by the
        # electric current.
        q = (C * V0) + (i * dt)
        # Calculate the voltage over the capacitor.
        V1 = q / C
        V1 = max(-1.0, min(V1, 1.0))
        
        return V1, i
    
    def process_pulse(self, tc, width):
    
        if width >= self.width_1200:
        
            self.current = "low"
            #print >>sys.stderr, "_"
            
            if self.state == "data":
                self.bits = self.bits >> 1
                self.shift += 1
                if self.debug:
                    print >>sys.stderr, "bit 0", tc, hex(self.bits), 
                    if self.shift == 8:
                        print >>sys.stderr, "<-", hex(self.bits), repr(chr(self.bits))
                    else:
                        print >>sys.stderr
            
            elif self.state == "ready":
            
                self.state = "data"
                if self.debug:
                    print >>sys.stderr, tc, self.state
                self.bits = 0
                self.shift = 0
            
            elif self.state == "after":
                raise ValueError("Expected high tone at %s (%.5f)." % (
                    hms(tc), tc - self.start_time))
            
            self.cycles = 0
        
        elif width >= self.width_2400 or (self.ymax > 0 and 2000 <= 1/(tc - self.last_tc) <= 3000):
        
            # The pulse was large enough to be a 1 pulse, or one occurred close
            # enough to where one might be expected.
            
            self.current = "high"
            #print >>sys.stderr, "*"
            
            if self.state == "waiting":
                self.state = "ready"
                if self.debug:
                    print >>sys.stderr, tc, self.state
            
            elif self.state == "data":
                self.cycles += 1
                if self.cycles == 2:
                    self.bits = (self.bits >> 1) | 0x80
                    self.shift += 1
                    self.cycles = 0
                    if self.debug:
                        print >>sys.stderr, "bit 1", tc, hex(self.bits),
                        if self.shift == 8:
                            print >>sys.stderr, "<-", hex(self.bits), repr(chr(self.bits))
                        else:
                            print >>sys.stderr
                
                elif self.debug:
                    print >>sys.stderr, "-", tc, hex(self.bits)
        
            elif self.state == "after":
                self.cycles += 1
                if self.cycles == 2:
                    self.state = "ready"
                    if self.debug:
                        print >>sys.stderr, tc, self.state
            
            if self.state == "ready" and self.adapt_frequency:
                f = 1/(tc - self.last_tc)
                target_dt = self.dt * (f/2400)
                self.dt = 0.5*(self.dt + target_dt)
        else:
            self.state = "waiting"
            return
        
        if self.shift == 8:
            self.state = "after"
            if self.debug:
                print >>sys.stderr, self.state, hex(self.bits), repr(chr(self.bits))
            self.shift = 0
            self.cycles = 0
            return self.bits
    
    def read_byte(self, audio_f):
    
        sign = None
        self.state = "waiting"
        self.current = None
        data = []
        self.bits = 0
        self.shift = 0
        self.cycles = 0
        self.ymax = 0
        
        # Low-pass filter constants
        resonant_f1 = self.f1
        R1 = 1000
        C1 = 1.0/(2 * math.pi * resonant_f1 * R1)
        
        # High-pass filter constants
        resonant_f2 = self.f2
        R2 = 1000
        C2 = 1.0/(2 * math.pi * resonant_f2 * R2)
        
        Vc1 = 0
        Vc2 = 0
        
        dt = self.dt
        old_y = 0
        y = 0
        dy = 0
        
        previous = None
        tc = 0
        self.last_tc = 0
        mean = 0.0
        
        start_t = None
        end_t = None
        
        floor_count = 0
        zero_count = self.zero_count
        mean_count = self.sample_rate/3900
        
        if self.debug:
            f = open("/tmp/debug.s8", "wb")
        
        if self.filter_:
            buf = []
        
        while True:
        
            sample = audio_f.read(self.step)
            if not sample:
                raise StopIteration
            
            if self.stop_time != None and self.T > self.stop_time:
                break
            
            try:
                values = struct.unpack(format, sample)
            except struct.error:
                raise StopIteration
            
            value = values[0]
            
            if self.filter_:
            
                buf.append(value)
                
                if len(buf) < 4:
                    self.T += self.dt
                    continue
                
                #print "", buf[0], buf[1], buf[2]
                
                # Check for a point that crosses the zero line out of sequence.
                if buf[0] * buf[1] < 0 and buf[0] * buf[2] > 0:
                
                    # Check for another crossing.
                    if buf[1] * buf[3] > 0:
                        # Interpolate the two middle points.
                        if self.debug:
                            print >>sys.stderr, " double spike at", hms(self.T), buf[0], buf[1], buf[2], buf[3], "->", (buf[1] + buf[3])/2.0
                        buf[1] = ((2 * buf[0]) + buf[3])/3.0
                        buf[2] = (buf[0] + (2 * buf[3]))/3.0
                    else:
                        # Interpolate the second point.
                        if self.debug:
                            print >>sys.stderr, " single spike at", hms(self.T), buf[0], buf[1], buf[2], buf[3], "->", (buf[0] + buf[2])/2.0
                        buf[1] = (buf[0] + buf[2])/2.0
                
                else:
                    b0 = buf[1] - buf[0]
                    b1 = buf[2] - buf[1]
                    b2 = buf[3] - buf[2]
                    if b0 * b1 < 0 and b0 * b2 > 0:
                    
                        # Interpolate the second point.
                        if self.debug:
                            print >>sys.stderr, " smoothing", hms(self.T), buf[0], buf[1], buf[2], buf[3], "->", (buf[0] + buf[2])/2.0
                        buf[2] = (buf[1] + buf[3])/2.0
                
                value = buf.pop(0)
                #print >>sys.stderr, value
            
            mean = ((mean * (mean_count - 1)) + value)/mean_count
            
            Vapp = (value - mean) * self.boost_factor/8.0
            # Apply the low-pass filter.
            Vc1, i1 = self.V(Vc1, Vapp, R1, C1, self.dt)
            # Apply the high-pass filter to the output of the low-pass filter.
            Vc2, i2 = self.V(Vc2, Vc1, R2, C2, self.dt)
            
            y = max(0.0, min(i2 * R2, 1.0))
            dy = y - old_y
            
            self.ymax = max(y, self.ymax)
            
            if self.debug:
                f.write(struct.pack("<b", y * 127))
            
            if old_y == 0 and y > 0 and start_t is None:
            
                start_t = self.T
                self.ymax = 0
                #print >>sys.stderr, "> %.5f" % (self.T - self.start_time)
            
            if dy < 0 and y == 0:
            
                end_t = self.T
                floor_count = 0
                #print >>sys.stderr, "< %.5f" % (self.T - self.start_time)
            
            elif y == 0 and start_t != None:
            
                floor_count += 1
                
                #print >>sys.stderr, "?", floor_count, zero_count
                
                if floor_count >= zero_count:
                
                    self.last_tc = tc
                    tc = (start_t + end_t)/2.0
                    width = end_t - start_t
                    
                    if self.debug:
                        print >>sys.stderr, "%.5f" % (tc - self.start_time), \
                        width/self.width_1200, width/self.width_2400
                    
                    if self.ymax > 0.1:
                        result = self.process_pulse(tc, width)
                        if result != None:
                            yield result
                    
                    floor_count = 0
                    start_t = None
            
            if not self.debug and not quiet:
                sys.stdout.write("\r%s " % hms(self.T))
            
            old_y = y
            self.T += self.dt
    
    def read_block(self, audio_f):
    
        gen = self.read_byte(audio_f)
        while True:
        
            byte = gen.next()
            
            if byte == 0x2a:
                try:
                    #print ">", self.T
                    yield Block(self.T, gen, self.debug)
                except ValueError:
                    raise


def check_wav(f, mono, sample_rate, sample_size):

    if not f.read(4) == "RIFF":
        f.seek(0, 0)
        return mono, sample_rate, sample_size
    
    f.seek(4, 1)
    
    if f.read(4) != "WAVE":
        raise IOError("Not a WAV file I understand.")
    
    if f.read(4) != "fmt ":
        raise IOError("Not a WAV file I understand.")
    
    header_size = struct.unpack("<I", f.read(4))[0]
    
    f.seek(4, 1)
    sample_rate = struct.unpack("<I", f.read(4))[0]
    f.seek(6, 1)
    
    sample_size = struct.unpack("<H", f.read(2))[0]
    
    if f.read(4) != "data":
        raise IOError("Not a WAV file I understand.")
    
    f.seek(4, 1)
    
    return mono, sample_rate, sample_size


if __name__ == "__main__":

    program_name, args = sys.argv[0], sys.argv[1:]
    
    r, sample_rate = find_option(args, "--rate", 1)
    mono = find_option(args, "--mono", 0)
    unsigned = find_option(args, "--unsigned", 0)
    s, sample_size = find_option(args, "--size", 1)
    start, start_time = find_option(args, "--start", 1)
    stop, stop_time = find_option(args, "--stop", 1)
    debug = find_option(args, "--debug", 0)
    right = find_option(args, "--right", 0)
    boost, boost_factor = find_option(args, "--boost", 1)
    use_f1, f1 = find_option(args, "--f1", 1)
    use_f2, f2 = find_option(args, "--f2", 1)
    set_width_1200, width_1200 = find_option(args, "--w1200", 1)
    set_width_2400, width_2400 = find_option(args, "--w2400", 1)
    set_zero_count, zero_count = find_option(args, "--zc", 1)
    filter_ = find_option(args, "--filter", 0)
    adapt_frequency = find_option(args, "--adapt", 0)
    quiet = find_option(args, "--quiet", 0)
    
    if len(args) != 2:
        sys.stderr.write("Usage: %s [--rate <sample rate in Hz>] [--mono] [--unsigned] [--size <sample size in bits>] [--start <time in seconds>] [--stop <time in seconds>] [--boost <factor>] [--filter] <audio file> <UEF file>\n" % program_name)
        sys.exit(1)
    
    audio_file = args[0]
    uef_file = args[1]
    
    if audio_file == "-":
        audio_f = sys.stdin
    else:
        audio_f = open(audio_file, "rb")
        mono, wav_sample_rate, sample_size = check_wav(audio_f, mono, sample_rate, sample_size)
        if not r:
            sample_rate = wav_sample_rate
        s = r = True
    
    if not s or not r:
        sys.stderr.write("Usage: %s [--rate <sample rate in Hz>] [--mono] [--unsigned] [--size <sample size in bits>] [--start <time in seconds>] [--stop <time in seconds>] [--boost <factor>] [--filter] <audio file> <UEF file>\n" % program_name)
        sys.exit(1)
    
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
    else:
        start_time = from_hms(start_time)
    
    if not boost_factor:
        boost_factor = 1.0
    
    if use_f1:
        f1 = float(f1)
    else:
        f1 = 1200.0
    
    if use_f2:
        f2 = float(f2)
    else:
        f2 = 1200.0
    
    if set_width_1200:
        width_1200 = 1/float(width_1200)
    else:
        width_1200 = 1/3200.0
        
    if set_width_2400:
        width_2400 = 1/float(width_2400)
    else:
        width_2400 = 1/7000.0
    
    if set_zero_count:
        zero_count = int(zero_count)
    else:
        zero_count = 6200
    
    step = int(sample_size/8)
    
    if right:
        audio_f.seek(step, 1)
    
    if sample_size == 8:
        format = "b"
    else:
        format = "h"
    
    if not mono:
        step = step * 2
        format = format * 2
    
    format = "<" + format
    reader = Reader(format, step, int(sample_rate), float(boost_factor),
                    f1, f2, width_1200, width_2400, zero_count,
                    filter_, adapt_frequency, quiet, debug)
    reader.start_at(float(start_time))
    print "Seeking to", float(start_time)
    audio_f.seek(step * float(start_time) * int(sample_rate), 1)
    
    if stop:
        reader.stop_at(from_hms(stop_time))
    
    last_T = 0
    data = []
    blocks = []
    
    try:
        for block in reader.read_block(audio_f):
            if not debug:
                print hms(block.T), block.name, hex(block.load_addr), hex(block.exec_addr), hex(block.number), block.length, hex(block.flags)
            else:
                print "%.2f (%s)" % (block.T, hms(block.T)), block.name, hex(block.load_addr), hex(block.exec_addr), hex(block.number), block.length, hex(block.flags)
            blocks.append(block)
    except:
        exc_type, exc, tb = sys.exc_info()
        sys.stderr.write(str(exc) + "\n")
        sys.exit(1)
    
    if not debug:
        print
    
    u = UEFfile.UEFfile(creator = 'recordUEF.py ' + version)
    u.minor = 6
    u.target_machine = "Electron"
    
    for block in blocks:
    
        if block.number == 0:
            u.chunks += [(0x112, u.number(2, 0x5dc)),
                         (0x110, u.number(2, 0x5dc)),
                         (0x100, u.number(1, 0xdc)),
                         (0x110, u.number(2, 0x5dc))]
        else:
            u.chunks.append((0x110, u.number(2, 0x258)))
        
        u.chunks.append((0x100, block.data()))
        
        if block.length < 256 or block.flags & 0x80:
            u.chunks.append((0x110, u.number(2, 0x258)))
    
    # Write the new UEF file.
    try:
        u.write(uef_file, write_emulator_info = False)
    except UEFfile.UEFfile_error:
        sys.stderr.write("Couldn't write the new executable to %s.\n" % uef_file)
        sys.exit(1)
    
    #sys.exit()
