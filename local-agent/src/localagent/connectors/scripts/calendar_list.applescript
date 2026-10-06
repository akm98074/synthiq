-- argv: startOffsetSeconds, endOffsetSeconds (relative to now)
-- out: one record per event: title US startOffset US endOffset US location US calendar US allday RS
on run argv
	set nowD to current date
	set s to nowD + ((item 1 of argv) as number)
	set f to nowD + ((item 2 of argv) as number)
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "Calendar"
		repeat with c in calendars
			set cname to name of c
			try
				set evs to (every event of c whose start date is greater than or equal to s and start date is less than or equal to f)
				repeat with e in evs
					set loc to ""
					try
						set loc to location of e
						if loc is missing value then set loc to ""
					end try
					set out to out & (summary of e) & US & ((start date of e) - nowD) & US & ((end date of e) - nowD) & US & loc & US & cname & US & (allday event of e) & RS
				end repeat
			end try
		end repeat
	end tell
	return out
end run
