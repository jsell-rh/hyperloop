## Agentic Loop Principles

- There are two primary loops used to reconcile a spec with code. 
	- 1) The outer loop determines the Sync status of the system (do specs align with code), and coordinates the inner loop mechanics.
	- 2) The inner loop fires when the system is OutOfSync and handles the "boots on the ground" coding work.
- Agent sessions MUST never assess their transition criteria (no self-grading.)
	- Instead, use a fresh session to assess the work of the other session.
	- Corollary: Agents cannot be trusted to determine Sync status of a spec & code. To address this,
		- 1) Fresh agentic sessions that assess sync status are used as a loop retry gate at the end of a reconciliation pass.
		- 2) Periodic spec sync scan catches falsely reported `Synced` statuses from persisting.
		- 3) Fundamentally different models may provide higher quality Sync assessment (i.e. Gemini & Claude vs Claude & Claude)
- If agents are permitted to request a routing decision, it MUST be permitted by a whitelist.
- Desired state is defined by spec files. Actual state is determined by an agent's assessment of a spec's implementation (`Synced`/`OutOfSync`)
	- Reconciliation states are defined as:
		- **OutOfSync** A spec whose blob sha @ HEAD is not marked as `Synced` or `Reconciling`, or is marked as `OutOfSync`
		- **Reconciling** A spec whose blob sha @ HEAD is marked as `Reconciling`
		- **Synced** A spec whose blob sha @ HEAD is marked as `Synced`
		- **Failed** A spec whose blob sha @ HEAD is marked as `Failed`
			- Failed state signals the need for human intervention. Failed may occur when there are irreconcilable issues/ambiguities in a spec, or the implementation loop has reached a maximum number of iterations (think: CrashBackOff)
	- Divergence is determined by one of three methods:
		- 1) The blob sha of a spec @ HEAD changes, and this new sha is not marked as `Synced` or `Reconciling`
			- Read: A spec is created or updated
		- 2) A periodic agent-powered spec sync scan results in a spec's blob sha being marked as `OutOfSync` 
			- Read: An existing spec is found to have an implementation that is not faithful to the spec.
- Specs must _only_ define desired state & verification steps. Work phases, timelines, status reporting, etc., do _not_ belong in the spec. 
	- NFRs may exist in specs, but they must declare a method of verification. 
- When a spec is determined to be `OutOfSync`, an agent MUST be used to break down an `OutOfSync` spec into units of work (tasks) that will be passed to the [inner] reconciliation loop.
	- The task decomposition agent (Controller) runs _serially_ (i.e. decomposes specs -> tasks for _all_ `OutOfSync` tasks.) to improve dependency identification.
	- The outer loop should mechanically pass the diff between last `Synced` blob sha (which could be null) and HEAD to the agent in charge of creating tasks. This allows the agent to short circuit if the changes are cosmetic only (eg. whitespace formatting, re-ordering a numbered list, etc.)
	- Units of work MUST declare their dependencies on other units of work, so that the outer loop can reconcile specs in the correct order.
	- This inner loop should be flexible/pluggable/portable/customizable and the outer loop and inner loops should not have to know about one another.


### Key Unanswered Questions
- Does this pattern guarantee convergence? 


```python
class Event:
  id: int
  type: Normal | Warning
  reason: str # Ex. TaskFailed
  count: int
  first_timestamp: datetime
  last_timestamp: datetime
  message: str
  
class TaskStatus(Enum):
  Backlog
  InProgress
  Complete
  Failed
  
class Task:
  id: int
  depends_on: tuple[int]
  spec_path: str # Is this circular dependency? 
  spec_blob_sha: str # Is this circular dependency? 
  name: str
  description: str
  status: TaskStatus
  events: list[Event]
  
class SpecStatus(Enum):
  OutOfSync
  Reconciling
  Verifying
  Synced
  Failed
  
class SpecPlan:
  path: str
  blob_sha: str
  status: SpecStatus
  superseded: bool # If yes, not considered
  implementation_tasks: list[Task]
  events: list[Event]
  
class Plan: 
  spec_plans: list[SpecPlan]
  events: list[Event]
  
  def get_next_monotonic_task_id(self) -> int:
    # Generate unique monotonic task ID across all specs
    ...
    
  def add_spec_idempotent(self, spec_path, spec_blob_sha): 
    # Adds a SpecPlan of the given sha if not exists, 
    # setting status to OutOfSync.
    # 
    # FURTHER, if the spec_path exists (1 or more) with a blob sha
    # that is different than what is passed here, all other specplans
    # that share a path but have different blob shas will be marked
    # as superseded.
    ...
  
  def get_spec_status(self, spec_path: str, spec_blob_sha: str) -> SpecStatus:
    ...
    
  def set_spec_status(self, spec_path: str, spec_blob_sha: str, status: SpecStatus):
    ...
    
  def update_task_status(self, task_id: int):
    # Updates task status, also sets parent Spec Status to Reconciling
    ...
    
  def add_tasks_to_plan(self, tasks: list[Task]):
    # Add tasks under the parent spec blob sha. 
    # Sets the status of the parent spec to SpecStatus.Reconciling.
    ...
    
  def get_unblocked_tasks(self) -> list[Task]:
    # Get tasks that, based on the task DAG across all specs, are unblocked and can be worked in parallel.
    # Filters out tasks with superseded parents.
    ...
    
  def create_task_failed_event(self, message: str, task_id: int):
    # Creates an event on the specified task (within a spec plan) with
    # Type Warning, Reason TaskFailed
    ...
    
class BranchStatus(Enum):
  Success
  Failure
  
class BranchResult:
  id: int
  spec_blob_sha: str
  status: BranchStatus
  status_rationale: Optional[str]
	
def get_plan() -> Plan:
  pull_plan_branch()
  # Reads plan.json from plan branch (ex. `hyperloop/plan`)
  return get_plan_from_plan_branch()
  
def write_plan(Plan):
  pull_plan_branch()
  write_plan_to_git(Plan)
  push_plan_branch()

while True:
	pull_trunk()
	
	plan = get_plan()

	for spec in get_specs_on_trunk():
	  plan.add_spec_idempotent(spec.path, spec.sha)
	
	specs_out_of_sync = [s for s in plan.spec_plans if s.status == SpecStatus.OutOfSync and not s.superseded]
	
	new_tasks = launch_spec_decomposition_agent(specs_out_of_sync) # Read-only agent
	plan.add_tasks_to_plan(new_tasks)
	
	
	# Solve DAG dependency graph
	unblocked_tasks = plan.get_unblocked_tasks()
		
	# Launch Inner Loop
	async for task in unblocked_tasks:
	
	  # Create a branch for the spec delivery, all tasks will
	  # merge into this once complete. This is the "PR Vehicle"
	  spec_branch = create_spec_branch_idempotent(task.spec_blob_sha) # eg. `hyperloop/spec/{blob_sha}`
	
	  task_branch = create_task_branch(task.id)
	  
	  # Single commit on the new task_branch that
	  # contains no file diff (empty commit). 
	  # Contains the task details, spec ref, and any 
	  # relevant events.
	  write_task_briefing(task, task_branch, plan.get_events(task))
	  
	  push(task_branch)
	  
	  plan.update_task_status(task, TaskStatus.InProgress)
	  
	  
	  launch_inner_loop_for_task(task_branch)
	  
	  
	write_plan(plan)
	  
	# Current Task States
	fetch_and_pull_all()
	  
	# Reads the latest commit on each `hyperloop/spec/{blob_sha}/task/*` which
	# MUST be an empty commit with the format:
	# <Summary of work/Rationale for Task-Status>
	# 
	# Task-Status: Complete | Failed
	current_tasks: list[BranchTask] = get_tasks_from_git()
	
	# Sync plan w/ current task state
	for task in current_tasks:
	
	  if task.status == TaskStatus.Complete:
	    plan.update_task_status(task.spec_blob_sha, task.id)
	    
	    # Need to handle conflicts
	    if merge_task_into_spec_branch(task):
		    delete_task_branch(task.id)
		else:
		    plan.event(task.id, "TaskMergeConflict", "Failed to merge <task> into <spec branch>")
	    
	    
	  if task.status == TaskStatus.Failed:
	    plan.create_task_failed_event(task.id)
	    
	  write_plan(plan)
	  
	# Launch async spec vs implementation verification agents
	async for spec in plan <where spec.tasks are all Complete AND spec.status == SpecStatus.Reconciling>:
	  # Creates (or deletes then creates) new branch from the spec branch, used to run the verification agent.
	  # The final empty commit is used to manage transitions
	  verification_branch = create_verification_branch(spec) # ex. hyperloop/spec/{blob_sha}/verifier
	  plan.set_spec_status(spec, SpecStatus.Verifying)
	  launch_verification_agent(spec)
	  
	  write_plan(plan)
	  
	# Check for verification status
	for spec in plan <where spec.status == SpecStatus.Verifying>:
		# Reads the latest commit on each `hyperloop/spec/{blob_sha}/verifier` which
		# MUST be an empty commit with the format:
		# <Summary of work/Rationale for Verification-Status>
		# 
		# Verification-Status: Pass | Fail
		verifier_status: BranchResult | None = get_verifier_status(spec)
		
		if verifier_status is None:
			continue
		
		if verifier_status.status == BranchResult.Failure:
			plan.event(spec, Warning, "VerifierFailed", verifier_status.status_rationale)
			
			plan.set_spec_status(spec, SpecStatus.OutOfSync)
			
		else:
			plan.event(spec, Normal, "VerifierPassed", verifier_status.status_rationale)
			
			
				if merge_to_trunk(spec): # Need to handle conflicts, this should probably be a PR? 
					plan.set_spec_status(spec, SpecStatus.Synced)
					
				else:
				    plan.event(spec, Warning, "VerifierMergeFailed", "Failed to merge <verifier_branch> into <spec branch>")
			    
	    write_plan(plan)
		
		
	sleep(30)
```
