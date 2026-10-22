//! Windows Job Object with kill-on-close (decision 0012, layer 3): the OS kills the engine tree when the shell dies.

use std::os::windows::io::AsRawHandle;
use std::process::Child;
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, TH32CS_SNAPTHREAD, THREADENTRY32, Thread32First, Thread32Next,
};
use windows_sys::Win32::System::JobObjects::*;
use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

pub const CREATE_SUSPENDED: u32 = 0x0000_0004;
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Put a process spawned with `CREATE_SUSPENDED` into a new kill-on-close job, then let it run.
/// The job handle is deliberately never closed: it lives as long as the shell, whatever way the shell ends.
pub fn confine_and_resume(child: &Child) -> Result<(), String> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err("CreateJobObjectW failed".into());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of_val(&info) as u32,
        ) == 0
        {
            return Err("SetInformationJobObject failed".into());
        }
        if AssignProcessToJobObject(job, child.as_raw_handle() as _) == 0 {
            return Err("AssignProcessToJobObject failed".into());
        }
    }
    resume(child.id())
}

fn resume(pid: u32) -> Result<(), String> {
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snap == INVALID_HANDLE_VALUE {
            return Err("thread snapshot failed".into());
        }
        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
        let mut resumed = false;
        let mut more = Thread32First(snap, &mut entry) != 0;
        while more {
            if entry.th32OwnerProcessID == pid {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                if !thread.is_null() {
                    resumed |= ResumeThread(thread) != u32::MAX;
                    CloseHandle(thread);
                }
            }
            more = Thread32Next(snap, &mut entry) != 0;
        }
        CloseHandle(snap);
        if resumed {
            Ok(())
        } else {
            Err("could not resume the engine".into())
        }
    }
}
