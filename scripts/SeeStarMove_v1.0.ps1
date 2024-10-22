# Do not alter the format of any of the comments below
# #####
# initial=Y
# workDir=
# rubbishDir=
# targetDir=
# outputCSV=
# uncPath=\\seestar\EMMC Images
# tempDrive=Z:
# removeSubJpg=Y
# removeJpg=T
# removeTxt=Y
# moveCopy=M
# performFullScan=N
# scanMsgLine=N
# displayScanMsg=F
# #####
# This script will pull all of the observation folders from a connected SeeStar telescope.
#
# Written by Steven Fox
#
# The folders from the SeeStar are initially placed in a work directory.
# Then based on settings some of these files will be moved into a rubbish directory.
#
# The remaining files will then be moved into your specified target directory.
#
# The end result is all your observations for a single target will appear in a single directory.
# As it added files into the target folder it will update a csv file that contains a summary of observations.
#
# If you already have observations in your target directory then you can ask the script to do a one off scan.
# You could also do this if for some reason your csv file got corrupted or if you manually made changes in your target directory.
# You do not need to run a full scan each time.
#
# Warning: This script is provided as is and the user must decide if they wish to run it.
#
# Warning: The script may not work correctly if ZWO adds functionality to the SeeStar or changes the format of the folders / files.
#
# Warning: I suggest you save the data on the SeeStar before you run this script for the first time, select an empty target
#          folder until you are happy with the script.
#
################################################################################################

# Define Patterns
	$patterns = @(
	# 1=Normal Light pattern
    "^Light_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",
	
	# 2=Light pattern with mosaic extra on target name
	"^Light_[A-Za-z0-9()'-.\s]+_\d+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",
	
	# 3=Normal Stacked pattern
	"^Stacked_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",
	
	# 4=Stacked pattern with number of images stacked
	"^Stacked_\d+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",	
	
	# 5=Stacked pattern with number of images stacked and Mosaic
	"^Stacked_\d+_[A-Za-z0-9()'-.\s]+_\d+_[A-Za-z0-9()'-.\s]+_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",

	# 6=Video Stacked pattern
	"^Video_Stacked_[A-Za-z0-9()'-.\s]+_\d{8}-\d{6}$",
	
    # 7=Non-DSO format containing only date-time and Target
    "^\d{4}-\d{2}-\d{2}-\d{6}-.+$"
	)

# Function to handle file moving based on the defined settings
function Move-File {
    param (
        [string]$file,
        [string]$rubbishDir,
        [string]$subFolderName
    )
    $target = Join-Path $rubbishDir $subFolderName
    if (-Not (Test-Path $target)) {
        New-Item -Path $target -ItemType Directory | Out-Null
    }
    Move-Item -Path $file -Destination $target -Force
}

# Function to log messages with a timestamp and support for temporary messages
function Write-Log {
    param (
        [string]$message,
        [bool]$showTimestamp = $true,
        [System.ConsoleColor]$color = [System.ConsoleColor]::White,
        [bool]$isTemp = $false
    )

    # Helper function to clear the current line
    function Clear-Line {
        $bufferWidth = $Host.UI.RawUI.BufferSize.Width
        $Host.UI.RawUI.CursorPosition = @{X=0; Y=($Host.UI.RawUI.CursorPosition.Y)}
        Write-Host (" " * $bufferWidth) -NoNewline
        $Host.UI.RawUI.CursorPosition = @{X=0; Y=($Host.UI.RawUI.CursorPosition.Y)}
    }
    if ($isTemp) {
        Clear-Line
        Write-Host "$message" -ForegroundColor $color -NoNewline
    } else {
        Clear-Line
        if ($showTimestamp) {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Write-Host "[$timestamp] $message" -ForegroundColor $color
        } else {
            Write-Host "$message" -ForegroundColor $color
        }
    }
}

# Function to handle message display based on $displayScanMsg
function Write-ProgressMessage {
    param (
        [string]$message,
        [string]$type = "Info" # Options: Info, Error, Folder
    )
    
    switch ($displayScanMsg) {
        "A" {
           if ($type -eq "Error") {
                Write-Log $message -isTemp $scanMsgOneLine -color Red
			} else {
				Write-Log $message -isTemp $scanMsgOneLine
            }
        }
        "F" {
            if ($type -eq "Error") {
                Write-Log $message -isTemp $scanMsgOneLine -color Red
			} elseif ($type -eq "Folder") {
				Write-Log $message -isTemp $scanMsgOneLine
            }
        }
        "E" {
            if ($type -eq "Error") {
                Write-Log $message -isTemp $scanMsgOneLine -color Red
            }
        }
    }
}

# Record end time
function Record-End-Time {
    $endTime = Get-Date
    $totalTime = $endTime - $startTime
    $minutes = [math]::floor($totalTime.TotalMinutes)
    $seconds = $totalTime.Seconds

    If ($minutes -eq "0") {
        Write-Log "All $scanCount folders processed successfully. Total time taken: $seconds Seconds" -color Yellow
    } else {
        Write-Log "All $scanCount folders processed successfully. Total time taken: $minutes Minutes $seconds Seconds" -color Yellow
    }
}

# Function to check if the UNC path exists
function Test-UNCPath {
    param (
        [string]$path
    )
    try {
        $result = Test-Path -Path $path
        return $result
    } catch {
        return $false
    }
}

# Function to read the variable from the comment line
function Get-Var {
    param (
        [string]$filePath,
        [string]$variableName
    )
    $content = Get-Content $filePath
    $inSection = $false
    foreach ($line in $content) {
        if ($line -eq "# #####") {
            $inSection = -not $inSection
            continue
        }
        if ($inSection -and $line -match "# $variableName=(.+)") {
            return $matches[1]
        }
    }
    return $null
}

# Function to update the variable in the comment line
function Set-Var {
    param (
        [string]$filePath,
        [string]$variableName,
        [string]$newValue
    )
    $content = Get-Content $filePath
    $inSection = $false
    for ($i = 0; $i -lt $content.Length; $i++) {
        if ($content[$i] -eq "# #####") {
            $inSection = -not $inSection
            continue
        }
        if ($inSection -and $content[$i] -match "# $variableName=(.+)") {
            $content[$i] = "# $variableName=$newValue"
            Set-Content -Path $filePath -Value $content -Force
            return
        }
    }
}

function Change-Settings {

	# Ask to update parameters
	Write-Host "Update program settings." -ForegroundColor Yellow
	Write-Host "    Enter a new value for each setting or just press Enter to keep the existing value." -ForegroundColor Yellow
	Write-Host "    Enter an asterick to get help for that setting." -ForegroundColor Yellow
	Write-Host "    Enter QUIT to exit." -ForegroundColor Yellow

	for ($i = 0; $i -lt $settingArray.GetLength(0); $i++) {
		if (-not $skip) {
			Write-Host ('-' * 100) -ForegroundColor White
			Write-Host ("{0,2}" -f $($i+1)),"-", $settingArray[$i, 1] -ForegroundColor White
			$value=Get-Var -filePath $scriptFilePath -variableName $settingArray[$i, 0]
			Write-Host "           Currently: " -NoNewline
			Write-Host $value -ForegroundColor Blue
		}
		$newValue = Read-Host "     Enter new value"

	# If the user provides a new value, update the variable in the comment line
		$skip=$False
		if ($newValue.ToUpper() -eq "QUIT") {
			return $false
		} elseif ($newValue -eq "") {
			if ($value -eq "") {
				Write-Host "`tYou must enter a value for this setting. Try again." -ForegroundColor Red
				$i--
				$skip=$True
			}
		} else {
			If ($newValue -eq "*") {
				Write-Host $settingArray[$i, 3] -ForegroundColor Green
				$i--
				$skip=$True
			} else {
				if ($settingArray[$i, 2] -ne "") {
					$newValue=$newValue.ToUpper()
					if ($settingArray[$i, 2] -notmatch "(^|,)$newValue($|,)") {
						Write-Host "`t$newValue is not valid for this setting. Try again." -ForegroundColor Red
						$i--
						$skip=$True
					} else {
						Set-Var -filePath $scriptFilePath -variableName $settingArray[$i, $j] -newValue $newValue
						Set-Variable -Name $settingArray[$i, 0] -Value $newValue
					}
				}
			}
		}
	}
	return
}

# Display all settings
function Display-Settings {
	Write-Host "`nCurrent Settings...`n" -ForegroundColor White
	for ($i = 0; $i -lt $settingArray.GetLength(0); $i++) {
		$value=Get-Var -filePath $scriptFilePath -variableName $settingArray[$i, 0]
		Write-Host ("{0,2}" -f $($i+1)),"-", $settingArray[$i, 1] -ForegroundColor White
		Write-Host "           Currently: " -NoNewline
		Write-Host $value -ForegroundColor Blue
	}
}

function Map-UNCDrive {
    param (
        [string]$uncPath,
        [string]$tempDrive
    )
    try {
        net use $tempDrive $uncPath /persistent:no | Out-Null
        return $true
    } catch {
        Write-Log "Error: Could not map to drive $tempDrive" -showTimestamp $false -color Red
        return $false
    }
}

function From-SeeStar {
	param (
    [string]$moveCopy,
    [string]$myWorksPath
    )
	# Check the SeeStar is still online
	if (-Not (Test-Path $myWorksPath)) {
		Write-Log "Error: SeeStar no longer visable.  Try turning back on." -showTimestamp $false -color Red
		return
	}	
	
	# Describe the actions to be taken based on variables
	Write-Host "`nThis option will perform the following actions based on the settings supplied:"
	Write-Host "  1. SeeStar location: " -NoNewline
	Write-Host $myWorksPath -ForegroundColor Blue
	if ($moveCopy -eq "M") {
		Write-Host "  2. Move data from the SeeStar to work directory: " -NoNewline
		Write-Host $workDir -ForegroundColor Blue
	} else {
		Write-Host "  2. Copy data from the SeeStar to work directory: " -NoNewline
		Write-Host $workDir -ForegroundColor Blue
	}
	Write-Host "  3. Move some files to the rubbish directory: " -NoNewline
	Write-Host $rubbishDir -ForegroundColor Blue
	Write-Host "     A. Move TXT files: " -NoNewline
	Write-Host $removeTxt -ForegroundColor Blue
	if ($removeSubJpg -eq "T") {
		Write-Host "     B. Move JPG files in '-sub' folders: " -NoNewline
		Write-Host "$removeSubJpg  (only files ending with _thn)" -ForegroundColor Blue
	} else {
		Write-Host "     B. Move JPG files in '-sub' folders: " -NoNewline
		Write-Host $removeSubJpg -ForegroundColor Blue
	}
	if ($removeJpg -eq "T") {
		Write-Host "     C. Move JPG files in other folders: " -NoNewline
		Write-Host "$removeJpg  (only files ending with _thn)" -ForegroundColor Blue
	} else {
		Write-Host "     C. Move JPG files in other folders: " -NoNewline
		Write-Host $removeJpg -ForegroundColor Blue
	}
	Write-Host "  4. Move the remaining files to the target directory: " -NoNewline
	Write-Host $targetDir -ForegroundColor Blue
	Write-Host "  5. Perform a full target folder analysis: " -NoNewline
	Write-Host $performFullScan -ForegroundColor Blue

	# Check if the output CSV file is locked by attempting to open it for writing
	try {
		$stream = [System.IO.File]::Open($outputCSV, 'OpenOrCreate', 'Write', 'None')
		$stream.Close()
	} catch {
		Write-Log "Error: Output CSV file is locked: $outputCSV" -showTimestamp $false -color Red
		return
	}

	# Ask for user confirmation to proceed
	$confirmation = Read-Host "`nDo you want to continue? (Y/N)"
	Write-Host ""
	if ($confirmation -ne "Y") {
		Write-Host "Operation cancelled by user."
		return
	}

	# Ensure the rubbish directory exists
	if (-Not (Test-Path $rubbishDir)) {
		New-Item -Path $rubbishDir -ItemType Directory | Out-Null
	}

	# Ensure the target directory exists
	if (-Not (Test-Path $targetDir)) {
		New-Item -Path $targetDir -ItemType Directory | Out-Null
	}

	# Record start time
	$startTime = Get-Date

	# Check if the MyWorks folder contains any files or directories
	$items = Get-ChildItem -Path $myWorksPath -Recurse
	if ($items.Count -eq 0) {
		Write-Log "Error: No files or directories found in the MyWorks folder." -showTimestamp $false -color Red
		return $false
	}

	# Create the csv file if it does not exist
	if (-Not (Test-Path -Path $outputCSV)) {
	"Folder Name,Date,Target Name,Mosaic Frame,Frame Count,Exposure,Filter,FIT Count,JPG Count,TXT Count,MP4 Count,AVI Count" | Out-File -FilePath $outputCSV -Encoding utf8
	}
	Write-Log "Start processing files on the SeeStar." -color Yellow
	$scanCount = 0

	# Copy or move the contents of each folder in MyWorks to the work directory
	$subFolders = Get-ChildItem -Path $myWorksPath -Directory
	foreach ($subFolder in $subFolders) {
		$scanCount++
		$workSubDir = Join-Path $workDir $subFolder.Name
		if (-Not (Test-Path $workSubDir)) {
			New-Item -Path $workSubDir -ItemType Directory | Out-Null
		}

		Write-Log "Starting processing of folder: $($subFolder.Name)"

		# Copy or move files in the current folder to the work directory
		if ($moveCopy -eq "M") {
			Move-Item -Path "$($subFolder.FullName)\*" -Destination $workSubDir -Force
			Remove-Item -Path $subFolder.FullName

		} else {
			Copy-Item -Path "$($subFolder.FullName)\*" -Destination $workSubDir -Recurse -Force
		}
		Remove-Objects($workSubDir)

		# Move the processed folder to the target directory
		$targetSubDir = Join-Path $targetDir $subFolder.Name
		if (-Not (Test-Path -Path $targetSubDir -PathType Container)) {
			New-Item -Path $targetSubDir -ItemType Directory | Out-Null
		}
		Get-ChildItem -Path $workSubDir -File -Force | ForEach-Object { Move-Item -Path $_.FullName -Destination $targetSubDir -Force }

		# Remove the empty work folder
		Remove-Item -Path "$workSubDir"

		Write-Log "Finished processing folder: $($subFolder.Name)"
	}
	Record-End-Time

	# Perform a full analysis of the target folder if requested.
	if ($performFullScan -eq "Y") {
		Full-Scan
	}
}

# Function to check filename against patterns and return pattern number or -1 if not found
function CheckPattern {
    param (
        [string]$filename
    )
	
    for ($i = 0; $i -lt $patterns.Length; $i++) {
		$currentPattern = $patterns[$i]
#		Write-Host "$filename - Current pattern: $currentPattern"
		
        if ($filename -match $currentPattern) {
            return $i + 1  # Return pattern number, +1 because array indices start at 0
        }
    }
    return -1  # If no match found
}

# Function: Full scan
function Full-Scan {

	# Check if the output CSV file is locked by attempting to open it for writing
	try {
		$stream = [System.IO.File]::Open($outputCSV, 'OpenOrCreate', 'Write', 'None')
		$stream.Close()
	} catch {
		Write-Log "Error: Output CSV file is locked: $outputCSV" -showTimestamp $false -color Red
		return
	}
	# Record start time
	$startTime = Get-Date
	write-host ""
	Write-Log "Perfoming full scan of Target Directory.  Results in $outputCSV" -color Yellow
	if ($scanMsgLine -eq "Y") {
		$scanMsgOneLine=$True
	} else {
		$scanMsgOneLine=$False
	}
	


	# Clear the output CSV file if it exists
	if (Test-Path -Path $outputCSV) {
		Remove-Item -Path $outputCSV
	}

	# Create CSV header
	"Folder Name,Date,Target Name,Mosaic Frame,Frame Count,Exposure,Filter,FIT Count,JPG Count,TXT Count,MP4 Count,AVI Count" | Out-File -FilePath $outputCSV -Encoding utf8

# Initialize a hashtable to store counts per date
	$datesWithCounts = @{}
	$scanCount = 0

	# Iterate through each folder in the top-level source folder
	Get-ChildItem -Path $targetDir -Directory | ForEach-Object {
		$scanCount++
		$parentFolderName = $_.Name
		$parentFolderPath = $_.FullName
		Write-ProgressMessage "Scanning folder: $parentFolderPath" "Folder"

		# Process files and count file types
		Get-ChildItem -Path $parentFolderPath -File | 
			Where-Object { $_.Extension -match "\.fit|\.jpg|\.txt|\.mp4|\.avi" } | 
			Sort-Object Extension, Name | 
			ForEach-Object {
			Write-ProgressMessage "Scanning file: $($_.Name)"
			$fileName = $_.BaseName
			$fileDate = ""
			$targetName = ""
			$mosaic = ""
			$frameCount = ""
			$exposure = ""
			$filter = ""
			$foundDate = $false

			# Initialize file type counters
			$fitCount = 0
			$jpgCount = 0
			$txtCount = 0
			$mp4Count = 0
			$aviCount = 0

			# Initialize counter for segments
			$segments = $fileName -split '_'
			$segmentCount = $segments.Length
			
			$patternNumber = CheckPattern -filename $filename
# read-host $patternNumber			
			if ($patternNumber -gt 0) {
#				Write-Host "File '$filename' matches pattern number $patternNumber"
				# Perform actions based on the matched pattern number
				switch ($patternNumber) {
					1 { # Normal Light pattern
						$targetName = $segments[1]
						$exposure = $segments[2]
						$filter = $segments[3]
						$fileDate = $segments[4].Substring(0, 8)
					}
					2 { # Light pattern with mosaic extra on target name
						$targetName = $segments[1]
						$mosaic = $segments[2]
						$exposure = $segments[3]
						$filter = $segments[4]
						$fileDate = $segments[5].Substring(0, 8)
					}
					3 { # Normal Stacked pattern
						$targetName = $segments[1]
						$exposure = $segments[2]
						$filter = $segments[3]
						$fileDate = $segments[4].Substring(0, 8)
					}
					4 { # Stacked pattern with number of images stacked
						$frameCount = $segments[1]
						$targetName = $segments[2]
						$exposure = $segments[3]
						$filter = $segments[4]
						$fileDate = $segments[5].Substring(0, 8)
					}
					5 { # Stacked pattern with number of images stacked and Mosaic
						$frameCount = $segments[1]
						$targetName = $segments[2]
						$mosaic = $segments[3]
						$exposure = $segments[4]
						$filter = $segments[5]
						$fileDate = $segments[6].Substring(0, 8)
					}
					6 { # Video Stacked pattern
						$targetName = $segments[2]
						$fileDate = $segments[3].Substring(0, 8)
					}
					7 { # Non-DSO format containing only date-time and Target
						$fileDate = $fileName.Substring(0, 10).Replace('-', '')
						$targetName = $fileName.Substring(18) 
					}
				}
			} else {
				$fileDate = $_.CreationTime.ToString("yyyyMMdd")
				Write-ProgressMessage "Filename format error for filename: $($_.Name). Using creation date: $fileDate" -Type "Error"
			}
			
			# Increment the corresponding file type counter
			switch ($_.Extension.ToLower()) {
				".fit" { $fitCount++ }
				".jpg" { $jpgCount++ }
				".txt" { $txtCount++ }
				".mp4" { $mp4Count++ }
				".avi" { $aviCount++ }
			}

			# Update the hashtable with counts
			if (-not $datesWithCounts.ContainsKey($fileDate)) {
				$datesWithCounts[$fileDate] = @{
					TargetName = $targetName
					Mosaic = $mosaic
					FrameCount = $frameCount
					Exposure = $exposure
					Filter = $filter
					FIT = 0
					JPG = 0
					TXT = 0
					MP4 = 0
					AVI = 0
				}
			}
			$datesWithCounts[$fileDate].FIT += $fitCount
			$datesWithCounts[$fileDate].JPG += $jpgCount
			$datesWithCounts[$fileDate].TXT += $txtCount
			$datesWithCounts[$fileDate].MP4 += $mp4Count
			$datesWithCounts[$fileDate].AVI += $aviCount
		}

		# Output counts to CSV for each date within the parent folder in chronological order
		$sortedKeys = $datesWithCounts.Keys | ForEach-Object { [datetime]::ParseExact($_, "yyyyMMdd", $null) } | Sort-Object

		# Output counts to CSV for each date within the parent folder
		foreach ($key in $sortedKeys) {
			$dateKey = $key.ToString("yyyyMMdd")
			$counts = $datesWithCounts[$dateKey]
			"$parentFolderName,$dateKey,$($counts.TargetName),$($counts.Mosaic),$($counts.FrameCount),$($counts.Exposure),$($counts.Filter),$($counts.FIT),$($counts.JPG),$($counts.TXT),$($counts.MP4),$($counts.AVI)" | Out-File -FilePath $outputCSV -Append -Encoding utf8
		}

		# Clear the hashtable for the next folder
		$datesWithCounts.Clear()
	}
Record-End-Time
}

function Initial-Cleanup {
	Write-host "`nYou have requested an Initial cleanup of " -NoNewline
	Write-host $targetDir -ForegroundColor Blue
	Write-host "  Move some files to the rubbish directory: " -NoNewline
	Write-host $rubbishDir -ForegroundColor Blue
	Write-host "     A. Move TXT files: " -NoNewline
	Write-host $removeTxt -ForegroundColor Blue
	if ($removeSubJpg -eq "T") {
		Write-host "     B. Move JPG files in '-sub' folders: " -NoNewline
		Write-host "$removeSubJpg  (only files ending with _thn)" -ForegroundColor Blue
	} else {
		Write-host "     B. Move JPG files in '-sub' folders: " -NoNewline
		Write-host $removeSubJpg -ForegroundColor Blue
	}
	if ($removeJpg -eq "T") {
		Write-host "     C. Move JPG files in other folders: " -NoNewline
		Write-host "$removeJpg  (only files ending with _thn)" -ForegroundColor Blue
	} else {
		Write-host "     C. Move JPG files in other folders: " -NoNewline
		Write-host $removeJpg -ForegroundColor Blue
	}
	$confirmation = Read-Host "`nDo you want to continue? (Y/N)"
	Write-Host ""
	if ($confirmation -ne "Y") {
		Write-Log "Operation cancelled by user." -showTimestamp $false
		return
	}
	# Record start time
	$startTime = Get-Date
	Write-Log "Starting first time processing of target folder." -color Yellow
	$scanCount = 0
	$subFolders = Get-ChildItem -Path $targetDir -Directory
	foreach ($subFolder in $subFolders) {
		$scanCount++		
		Write-Log "Starting processing of folder: $($subFolder.Name)"
		$targetSubDir = Join-Path $targetDir $subFolder.Name
		Remove-Objects($targetSubDir)
		Write-Log "Finished processing folder: $($subFolder.Name)"
	}
	Record-End-Time
}

# Remove objects from a directory to the rubbish directory
Function Remove-Objects	{
    param (
        [string]$sourceDir
    )
	# Handle removal of specific file types based on settings
	if ($removeTxt -eq "Y") {
		Get-ChildItem -Path $sourceDir -Filter "*.txt" -File -Force | ForEach-Object {
			Move-File -file $_.FullName -rubbishDir $rubbishDir -subFolderName $subFolder.Name
		}
	}
	if ($subFolder.Name.EndsWith("-sub")) {
		if ($removeSubJpg -eq "Y") {
			Get-ChildItem -Path $sourceDir -Filter "*.jpg" -File -Force | ForEach-Object {
				Move-File -file $_.FullName -rubbishDir $rubbishDir -subFolderName $subFolder.Name
			}
		} elseif ($removeSubJpg -eq "T") {
			Get-ChildItem -Path $sourceDir -Filter "*_thn.jpg" -File -Force | ForEach-Object {
				Move-File -file $_.FullName -rubbishDir $rubbishDir -subFolderName $subFolder.Name
			}
		}
	} else {
		if ($removeJpg -eq "Y") {
			Get-ChildItem -Path $sourceDir -Filter "*.jpg" -File -Force | ForEach-Object {
				Move-File -file $_.FullName -rubbishDir $rubbishDir -subFolderName $subFolder.Name
			}
		} elseif ($removeJpg -eq "T") {
			Get-ChildItem -Path $sourceDir -Filter "*_thn.jpg" -File -Force | ForEach-Object {
			Move-File -file $_.FullName -rubbishDir $rubbishDir -subFolderName $subFolder.Name
			}
		}
	}
}

# Display SeeStar drive information
Function Check-SeeStar {
	$myWorksPath = $null
	$errorOccurred = $false
	# Get all drives and look for the one with the label "SeeStar"
	Write-Log -message "Searching for SeeStar via USB......." -isTemp $true
	$seeStarDrive = Get-WmiObject -Class Win32_LogicalDisk | Where-Object { $_.VolumeName -eq "SeeStar" }
	if ($null -eq $seeStarDrive) {
		Write-Log -message "Searching for SeeStar via WiFi (UNC)..." -isTemp $true

		# SeeStar not connected via USB - Try UNC path
		if (-Not (Test-Path -Path $uncPath)) {
			Write-Log "SeeStar USB drive or UNC path not found." -showTimestamp $false -color Red
			$errorOccurred = $true
		} else {
			if (-not (Map-UNCDrive -uncPath $uncPath -tempDrive $tempDrive)) {
				$errorOccurred = $true
			} else {
				$seeStarDrive = Get-WmiObject -Class Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $tempDrive }
				net use $tempDrive /delete /y | Out-Null

				if ($seeStarDrive) {
					$myWorksPath = Join-Path $uncPath "MyWorks"
				} else {
					Write-Log "Error: Could not retrieve SeeStar drive information." -showTimestamp $false -color Red
					$errorOccurred = $true
				}
			}
		}
	} else {
		# Define the MyWorks folder path
		$myWorksPath = Join-Path $seeStarDrive.DeviceID "MyWorks"
	}
	if ($myWorksPath -ne $null) {
		if (-Not (Test-Path -Path $myWorksPath)) {
			Write-Log "SeeStar path no longer found. $myWorksPath" -showTimestamp $false -color Red
		} else {
			Write-Log "Found a SeeStar at $myWorksPath.`n" -showTimestamp $false -color Yellow

			# Get SeeStar Capacity information
			$totalCapacityGB = [math]::round($seeStarDrive.Size / 1GB, 2)
			$freeSpaceGB = [math]::round($seeStarDrive.FreeSpace / 1GB, 2)
			$usedSpaceGB = [math]::round(($seeStarDrive.Size - $seeStarDrive.FreeSpace) / 1GB, 2)
			$freePercent = [math]::round($freeSpaceGB*100/$totalCapacityGB, 0)
			$usedPercent = [math]::round($usedSpaceGB*100/$totalCapacityGB, 0)

			# Adjust for alignment
			$totalCapacityGBStr = "{0,12}" -f "$totalCapacityGB GB"
			$usedSpaceGBStr = "{0,12}" -f "$usedSpaceGB GB"
			$freeSpaceGBStr = "{0,12}" -f "$freeSpaceGB GB"

			Write-Log "Total Capacity: $totalCapacityGBStr" -showTimestamp $false
			Write-Log "    Used Space: $usedSpaceGBStr ($usedPercent%)" -showTimestamp $false
			Write-Log "    Free Space: $freeSpaceGBStr ($freePercent%)" -showTimestamp $false
			Write-Log "Checking for files......" -showTimestamp $false -isTemp $True
			$fileCount = (Get-ChildItem -Path $myWorksPath -Recurse | Measure-Object).Count
			if ($fileCount -eq 0) {
				Write-Log "`nMyWorks folder is empty." -showTimestamp $false -color Red
			} else {
				Write-Log "Counting files......" -showTimestamp $false -isTemp $True
				$folderCount = (Get-ChildItem -Path $myWorksPath -Recurse | Where-Object { $_.PSIsContainer } | Measure-Object).Count
				$fileCountStr = "{0,9}" -f "$fileCount"
				Write-Log "         Files: $fileCountStr (in $folderCount folders)" -showTimestamp $false
			}
		}
	}
	Return $myWorksPath
}

################################################################################################
# Main script

$settingArray = New-Object 'object[,]' 13, 4

# Populate the array
$settingArray[0,0] = "targetDir"
$settingArray[0,1] = "The folder location where you are going to store all your SeeStar files."
$settingArray[0,3] = "`tThis is the folder on your PC where all the SeeStar files will be moved or copied to.`n" `
						+ "`tIf the folder does not exist it will be created."
$settingArray[1,0] = "workDir"
$settingArray[1,1] = "A work folder for the script to use."
$settingArray[1,3] = "`tThis is a temporary folder used by the script.  At the end the folder should be empty."
$settingArray[2,0] = "rubbishDir"
$settingArray[2,1] = "The location to store any files you asked the script to remove."
$settingArray[2,3] = "`tThis is the folder where all files you ask to be removed are stored.`n" `
						+ "`tYou can delete the contents when you are happy you no longer require them.`n" `
						+ "`tIf the folder does not exist it will be created."
$settingArray[3,0] = "outputCSV"
$settingArray[3,1] = "The name of the csv file to contain a list of your observations."
$settingArray[3,3] = "`tThis is the name of the CSV file that will store a summary of the data transfered from the SeeStar.`n" `
						+ "`tThe CSV file contains the following information.`n" `
						+ "`tIf the file does not exist it will be created."
$settingArray[4,0] = "UNCPath"
$settingArray[4,1] = "Wifi UNC address.  Usually \\seestar\EMMC Images"
$settingArray[4,3] = "`tThis is the WiFi UNC address for your SeeStar. It will be used if you dont connect the SeeStar via USB.`n" `
						+ "`tThe default '\\seestar\EMMC Images' should work unless you have changed it on the seestar."
$settingArray[5,0] = "tempDrive"
$settingArray[5,1] = "Free drive letter to use for WiFi copy.  Defaults to Z: but you can use any letter from K:"
$settingArray[5,2] = "K:,L:,M:,N:,O:,P:,Q:,R:,S:,T:,U:,V:,W:,X:,Y:,Z:"
$settingArray[5,3] = "`tTo be able to connect to a UNC address over WiFi it must be mounted to a drive letter.`n" `
						+ "`tThe default is Z: but if you already use this drive letter on your PC then change this to a free letter.`n"
$settingArray[6,0] = "removeSubJpg"
$settingArray[6,1] = "Remove JPG files from the -sub folders.  (N=No, Y=Yes, T=Just _thn files)"
$settingArray[6,2] = "N,Y,T"
$settingArray[6,3] = "`tThis script can remove some of the files produced by the SeeStar if you dont need them.`n" `
						+ "`tThe files will be placed in the rubbish folder you specified.`n" `
						+ "`tThis setting relates to the JPG files in the -sub folders.  The Options are...`n" `
						+ "`t`tN=Dont remove any.`n" `
						+ "`t`tY=Remove all JPG files.`n" `
						+ "`t`tT=Remove only the files ending with _thn.`n"
$settingArray[7,0] = "removeJpg"
$settingArray[7,1] = "Remove JPG files from the other folders.  (N=No, Y=Yes, T=Just _thn files)"
$settingArray[7,2] = "N,Y,T"
$settingArray[7,3] = "`tThis script can remove some of the files produced by the SeeStar if you dont need them.`n" `
						+ "`tThe files will be placed in the rubbish folder you specified.`n" `
						+ "`tThis setting relates to the JPG files in the folders not ending in -sub.  The Options are...`n" `
						+ "`t`tN=Dont remove any.`n" `
						+ "`t`tY=Remove all JPG files.`n" `
						+ "`t`tT=Remove only the files ending with _thn.`n"
$settingArray[8,0] = "removeTxt"
$settingArray[8,1] = "Remove TXT files from all folders.  (N=No, Y=Yes)"
$settingArray[8,2] = "N,Y"
$settingArray[8,3] = "`tThis script can remove some of the files produced by the SeeStar if you dont need them.`n" `
						+ "`tThe files will be placed in the rubbish folder you specified.`n" `
						+ "`tThis setting relates to all TXT files.  The Options are...`n" `
						+ "`t`tN=Dont remove any.`n" `
						+ "`t`tY=Remove all TXT files.`n"
$settingArray[9,0] = "moveCopy"
$settingArray[9,1] = "Move or Copy the files from the SeeStar.  (M or C)"
$settingArray[9,2] = "M,C,B"
$settingArray[9,3] = "`tDo you want to move the files from the SeeStar or leave them there after copying to your target folder.`n" `
						+ "`tEventually you will want to move them but until you are happy the script is working you should use copy.  The Options are...`n" `
						+ "`t`tC=Copy the files leaving them untouched on the SeeStar.`n" `
						+ "`t`tM=Move the files from the SeeStar leaving an empty SeeStar ready for your next viewing session.`n"
$settingArray[10,0] = "performFullScan"
$settingArray[10,1] = "Do you want to perform a full scan after each move/copy.  (N or Y)"
$settingArray[10,2] = "N,Y"
$settingArray[10,3] = "`tThis script will add a summary of the files moved or copied from the SeeStar into a csv file.`n" `
						+ "`tYou can get the script to do a full scan of the target folder after each run of this script.`n" `
						+ "`tThe options are...`n" `
						+ "`t`tN=Dont run the full scan each time.`n" `
						+ "`t`tY=Run a full scan each time.`n"
$settingArray[11,0] = "displayScanMsg"
$settingArray[11,1] = "What messages to display when doing a scan. (A = All, F = Folder and Error, E = Error only, N = None)"
$settingArray[11,2] = "N,A,E,F"
$settingArray[11,3] = "`tWhen processing files from the SeeStar or when running a full scan what messages should be shown on the screen.`n" `
						+ "`tThe options are...`n" `
						+ "`t`tN=No messages.`n" `
						+ "`t`tE=Only error messages.`n" `
						+ "`t`tF=Folder and error messages.`n" `
						+ "`t`tA=All messages including a line for every file processed.`n"
$settingArray[12,0] = "scanMsgLine"
$settingArray[12,1] = "Show scan messages on a single line. (N or Y)"
$settingArray[12,2] = "N,Y"
$settingArray[12,3] = "`tShould the scan messages be shown on a single line.  The options are...`n" `
						+ "`t`tN=Each message will appear on a separate line and scroll up.`n" `
						+ "`t`tY=Each message will overwrite the previous message on a single line.`n"

# Define the path to the script file
$scriptFilePath = $MyInvocation.MyCommand.Path

# If first time running script then force the user through the setup Process
$value=Get-Var -filePath $scriptFilePath -variableName "initial"
If ($value -eq "Y") {
	If (Change-Settings) {
		Set-Var -filePath $scriptFilePath -variableName "initial" -newValue "N"
	} else {
		exit
	}
}

# Copy all values from the comment lines into actual variables
for ($i = 0; $i -lt $settingArray.GetLength(0); $i++) {
	$value=Get-Var -filePath $scriptFilePath -variableName $settingArray[$i, 0]
	Set-Variable -Name $settingArray[$i, 0] -Value $value
}

$myWorksPath = Check-SeeStar

# Main Menu
while ($True) {
	Write-Host "`nSeeStar Menu`n" -ForegroundColor White
	if ($myWorksPath -ne $null) {
		if ($moveCopy -eq "M") {
			Write-Host "  M. Move data from the SeeStar to the target folder."
		}
		elseif ($moveCopy -eq "C") {
			Write-Host "  C. Copy data from the SeeStar to the target folder."
		}
		Write-Host "  E. Open Explorer window to SeeStar."
	}
	Write-Host "  D. Display settings."
	Write-Host "  S. Change settings."

	Write-Host "  F. Full scan of target folder."
	Write-Host "  I. Initial cleanup of objects from target folder."
	Write-Host "  Enter to reconnect to SeeStar."
	$menuOpt = Read-Host "`nEnter option or Exit"
	switch ($menuOpt.toUpper()) {
		"EXIT" {exit}
		"" {$myWorksPath = Check-SeeStar}
		"M" {From-SeeStar "M" $myWorksPath}
		"C" {From-SeeStar "C" $myWorksPath}
		"D" {Display-Settings}
		"E" {Invoke-Item -Path $myWorksPath}
		"S" {Change-Settings}
		"F" {Full-Scan}
		"I" {Initial-Cleanup}
		default {Write-Host "Invalid option. Please try again." -ForegroundColor Red}
	}
}
Read-Host "Should not get here:"
