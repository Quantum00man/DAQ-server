###This is a test code to see if DAQ is working or not#####
###tpye 'sudo python3 Testcodev0.py' to run. Make sure your trigger is working###
import ctypes
import libvkdaq
from ctypes import *
import matplotlib.pyplot as plt
import numpy as np


def main():
    task = "VkDaqTaskHandle"
    chans = "dev1/AIN1"
    chan_DigRef = "dev1/DIN1.1"
    fsamp = 4000
    data = (ctypes.c_double * 4000)()

    # VkDaq Configure Code
    libvkdaq.VkDaqCreateTask(c_char_p(task.encode('utf-8')))
    libvkdaq.VkDaqCreateAIVoltageChan(c_char_p(task.encode('utf-8')),c_char_p(chans.encode('utf-8')),c_char_p("".encode('utf-8')), libvkdaq.VkDaq_Val_SingleEnded, -0.0025, 0.0025, libvkdaq.VkDaq_Val_Volts,c_char_p("".encode('utf-8')))
    libvkdaq.VkDaqCfgSampClkTiming(task.encode('utf-8'), libvkdaq.VkDaq_Val_ClkSrc_OnBoardClk, fsamp,libvkdaq.VkDaq_Val_Rising, libvkdaq.VkDaq_Val_FiniteSamps, 400)
    #libvkdaq.VkDaqCfgDigEdgeRefTrig(task.encode('utf-8'),c_char_p(chan_DigRef.encode('utf-8')),libvkdaq.VkDaq_Val_Rising,0)
   
    truc = 0

    while truc == 0:
        libvkdaq.VkDaqCfgDigEdgeRefTrig(task.encode('utf-8'),c_char_p(chan_DigRef.encode('utf-8')),libvkdaq.VkDaq_Val_Rising,0)
        # VkDaq Start Code
        libvkdaq.VkDaqStartTask(c_char_p(task.encode('utf-8')))
        print("Waiting for digital triggering.\n")

        while True:
            # VkDaq Read Code
            read=libvkdaq.VkDaqGetTaskData(c_char_p(task.encode('utf-8')), data, 4000, libvkdaq.VkDaq_Val_GroupByChannel, 1)
            if read > 0:
                print(read)
                print(list(data))
                read = 0
                break

        libvkdaq.VkDaqStopTask(c_char_p(task.encode('utf-8')))
        #print("End of program, press Enter key to quit\n")

        '''#fig, ax = plt.subplots()
        t = np.linspace(0, 1, len(list(data)))
        diff = []
        for i in range (len(list(data))):
            diff.append((0.001*np.sin(i*2*np.pi*100*(1/fsamp)) - list(data)[i])**2)

        std = np.std(0.001*np.sin(t*2*np.pi*100) - list(data))
        print(std)
        #ax.plot(t, list(data), 'r-')
        #ax.plot(t, 0.001*np.sin(t*2*np.pi*100), 'g-')
        #ax.plot(t, diff, 'b-')

        #plt.show()
        #np.savetxt("test_acq.dat", data)'''
    libvkdaq.VkDaqClearTask(c_char_p(task.encode('utf-8')))

if __name__ == "__main__":
    main()
