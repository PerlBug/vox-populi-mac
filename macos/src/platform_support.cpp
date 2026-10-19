#include "CvGameCoreDLLPCH.h"
#include <mach/mach.h>

// Native counterpart of the optional Windows process-memory log. Query the
// current task directly rather than emulate process handles and psapi.h.
void PrintMemoryInfo(const char* hint) {
    task_vm_info_data_t info{};
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO,
                  reinterpret_cast<task_info_t>(&info), &count) != KERN_SUCCESS ||
        count < TASK_VM_INFO_REV1_COUNT) return;
    CUSTOMLOG("%s:\tResidentSize\t%llu kB\tPhysicalFootprint\t%llu kB", hint,
              static_cast<unsigned long long>(info.resident_size / 1024),
              static_cast<unsigned long long>(info.phys_footprint / 1024));
}
