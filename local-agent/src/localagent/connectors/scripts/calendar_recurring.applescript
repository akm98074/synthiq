-- argv: endOffsetSeconds (relative to now)
-- Returns every repeating series that starts before the window end, so Python can expand
-- its RRULE (AppleScript's "whose start date" only matches a series' first occurrence).
-- out: title US start US end US location US calendar US allday US rrule US excludedDates(comma) RS
-- Dates are exact local "YYYY-MM-DD HH:MM:SS" built from components (no second offsets).
on pad(n)
	set s to (n as integer) as string
	if (length of s) < 2 then set s to "0" & s
	return s
end pad

on fmt(d)
	set t to time of d
	return ((year of d) as integer as string) & "-" & my pad(month of d as integer) & "-" & my pad(day of d) & " " & my pad(t div 3600) & ":" & my pad((t mod 3600) div 60) & ":" & my pad(t mod 60)
end fmt

on run argv
	set f to (current date) + ((item 1 of argv) as number)
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "Calendar"
		repeat with c in calendars
			set cname to name of c
			try
				try
					set evs to (every event of c whose recurrence is not missing value and start date is less than or equal to f)
				on error
					set evs to (every event of c whose start date is less than or equal to f)
				end try
				repeat with e in evs
					set rr to missing value
					try
						set rr to recurrence of e
					end try
					if rr is not missing value and rr is not "" then
						set loc to ""
						try
							set loc to location of e
							if loc is missing value then set loc to ""
						end try
						set exl to ""
						try
							repeat with x in (excluded dates of e)
								set exl to exl & (my fmt(x)) & ","
							end repeat
						end try
						set out to out & (summary of e) & US & (my fmt(start date of e)) & US & (my fmt(end date of e)) & US & loc & US & cname & US & (allday event of e) & US & rr & US & exl & RS
					end if
				end repeat
			end try
		end repeat
	end tell
	return out
end run
