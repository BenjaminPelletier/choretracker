# choretracker user manual

choretracker is focused on two types of users:

1. The "child" user who sees and completes their chores
2. The "parent" user who defines and manages chores

## Children

### Viewing chores

Chore instances have a "start time" (*earliest time it would make sense to start working on the chore*) and a deadline. The home screen shows the active chore instances (*ones whose start time has passed but deadline is still in the future*) along with the next few upcoming chore instances. If any chore instances' deadlines have passed without being checked off, those chore instances are listed in an "Overdue" section and can only be checked off by a parent, presumably after determining an appropriate consequence.

### Checking off chores

To check off a chore as complete, the child must first switch to their profile. The active profile is shown via icon in the upper right and the eye icon indicates no specific profile is active. Touch the icon to switch profiles, then touch the checkbox of the chore to mark complete.

## Parents

Most parental actions can only be performed when the parent's profile is active. Click on the user icon in the upper right (an eye icon when no profile is active) to switch into the parent profile (entering PIN number if needed).

### Creating chores

A chore is a type of task that needs to be completed and may recur many times. Each recurrence is a chore instance. A parent creates a chore by touching the list icon in the menu bar and selecting Chore, then touching the \+.

#### Timing

Every chore instance has some time when it starts to make sense to do the chore. It wouldn't make sense to take out the weekly garbage two weeks early, for instance. This is the start time of the chore instance, and a chore can define a start time that repeats according via drop-down (weekly, monthly on a particular day of the month, etc). The specified start time is used for future instances; for instance, a start time on a Tuesday will repeat weekly on Tuesday if "weekly" is selected.

The duration of the chore can be defined directly according to how long after the start time the deadline occurs (e.g., 24 hours), or it can be defined according to the deadline; click the hourglass to toggle between these different deadline/duration definitions.

If a chore has a particular recurrence schedule but instances shouldn't actually start until a particular date, "None before" can be used to specify that no instances of the chore occur before this date regardless of the defined start time.

If a chore becomes obsolete at some point and therefore no instances should occur after a particular date, "None after" can be used to specify this.

#### Managers

Managers are users authorized to manage the chore, like checking instances off even when they're overdue, and skipping or modifying particular instances of the chore. These are generally the parents.

#### Responsible user

This is the user usually responsible for the chore; their icon will be shown next to the chore.

#### Title and description

The title should be brief and is what the chore will be listed as. The description can contain additional information about the chore (like completion criteria) and accepts Markdown.

### Managing a chore

#### Exceptions

To change a single instance of a chore but not the chore itself (e.g., give an extra day to wash the dishes this weekend, add an extra room to dust this Wednesday), view the chore instance by touching it from the home screen (or from the list of instances on the chore page itself). From here, the chore instance can be skipped (button) or modified (various pen icons). Save changes with the disk icon.

The timing (including deadline), person responsible, whether the instance has been completed, whether to skip the instance, and additional notes can all be adjusted here.

### Changing chores

#### Can't change the past

Chores may evolve over time, but choretracker retains a history of what actually happened, so chores with any instances in the past cannot be modified directly. Instead, when a user modifies them, the chore is split in two: the chore as it was with previous instances with no instances after the time of edit, and the chore as it was modified with no instances before the edit time.

#### Modifying chores

To modify a chore, first find the chore itself and not an instance of the chore. Each chore instance page contains a link to the chore itself in the page title. On the chore page, edit information with the pen icons and save those changes with the disk icon.

### Managing users

An admin user creates and manages other users and their permissions. When first deployed, there is a single admin user, though that user can then create other admin users. When an admin user's profile is active, user management can be found at the multiple-people icon under the gear icon.

A password is only needed if the user will log into the site from an unfamiliar device. Once logged in, the device remains logged in until logged out (though the active profile is automatically deactivated after a certain amount of time).

A PIN is only needed if access to the user profile needs to be protected; for instance, a single child probably does not need a PIN.

Profile pictures are highly recommended for an optimal experience.

### Other calendar entries

Reminders are similar to chores except they cannot be completed; they are simply reminders that appear during their active time. Events are like reminders except they actually happen throughout their active time.

## Examples

### Feed the dog

The dog needs to be fed twice a day: once in the morning and once in the evening. The child leaves for school at 7:30AM, so the morning feedings have a deadline of 7:30AM. The earliest the child might wake up is 5AM, so this chore gets 5 Weekly Recurrences, each starting at 5AM on a different weekday (e.g., Feb 23, 24, 25, 26, 27 in 2026) and each lasting 2.5 hours/ending 7:30AM.

The child gets home at 3PM, but that's too early to feed the dog. Instead, 5PM is the earliest it should be fed. The child's bedtime is 9:30PM and they need to start getting ready for bed at 9PM, so this chore gets 5 more Weekly Recurrences, each starting at 5PM on a different weekday (as above) and each lasting 4 hours/ending 9PM, except Friday where it lasts 4 hours 30 minutes/9:30PM.

On the weekends, things are more relaxed so 2 more morning Weekly Recurrences are added to start at 5AM and end at 10AM for Feb 28 and March 1 (Saturday and Sunday, respectively).  Finally, evening Weekly Recurrences are added from 5PM to 9:30PM for Feb 28 and 5PM to 9PM for March 1.

The child will be on an overnight field trip on March 4, so the parent selects the instance of this chore occurring 5-7:30AM March 4 and changes the responsible person to the parent.

The family will be on a trip March 7, so the parent selects each of the two instances that day and touches the "Skip instance" button.

The child has Monday March 16 off, so the parent modifies the morning instance this day to end at 10AM rather than 7:30AM.

In summer, there is no school so the parent edits the chore itself to move the deadline of all weekday Recurrences to 10AM.

### Laundry

Laundry needs to be done once a week. Weekend schedules are unpredictable with trips, etc, but there is almost always time Monday evenings. It wouldn't make sense to do laundry again just after it was done, so this chore gets one Weekly Recurrence from Thursday 3PM to Monday 9PM.

### School pick up

A parent needs to pick up the child from school on Tuesdays and Thursdays. This isn't a task that can ever not be done, so they create a Reminder for the parent that appears between 8AM and 3PM on Tuesdays and Thursdays. When something extra needs to be done for a specific pickup, an additional note can be added to the reminder, and the parent makes a habit to check the description briefly just before leaving every day.
