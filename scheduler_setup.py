"""
Registers (or updates) the ApartmentScanner Windows Task Scheduler job.
Run this directly or from setup.py.
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "ApartmentScanner"


def _python_path() -> str:
    return sys.executable


def register_task(project_dir: str | None = None) -> None:
    if project_dir is None:
        project_dir = str(Path(__file__).parent)

    python_exe = _python_path()
    main_py = str(Path(project_dir) / "main.py")

    # Build Task Scheduler XML for full control over StartWhenAvailable
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2024-01-07T08:00:00</StartBoundary>
      <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Sunday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>{main_py}</Arguments>
      <WorkingDirectory>{project_dir}</WorkingDirectory>
    </Exec>
  </Actions>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>"""

    xml_file = Path(project_dir) / "_task_temp.xml"
    xml_file.write_text(xml, encoding="utf-16")

    try:
        # Delete existing task if present (ignore errors)
        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
        )

        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_file)],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"[OK] Task '{TASK_NAME}' registered in Windows Task Scheduler.")
            print("     Runs every Sunday at 08:00. StartWhenAvailable=true (catches up if PC was off).")
        else:
            print(f"[FAIL] schtasks returned code {result.returncode}")
            print(result.stderr)
    finally:
        xml_file.unlink(missing_ok=True)


if __name__ == "__main__":
    register_task()
