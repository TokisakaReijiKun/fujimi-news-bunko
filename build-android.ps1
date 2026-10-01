param(
  [string]$Gradle = "",
  [switch]$Clean,
  [switch]$Release
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$android = Join-Path $repo "android"
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif (Test-Path -LiteralPath "C:\Android\Sdk") { "C:\Android\Sdk" } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }
if (-not (Test-Path -LiteralPath (Join-Path $sdk "platforms\android-36\android.jar"))) {
  throw "Android SDK platform android-36 not found. Install it with sdkmanager before building."
}

if (-not $Gradle) {
  $Gradle = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE ".gradle\wrapper\dists") -Filter gradle.bat -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "gradle-9\.6(?:\.0)?\\bin\\gradle\.bat$" } |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Gradle) { throw "Gradle 9.6 was not found. Pass -Gradle with a gradle.bat path." }

$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$signingDir = Join-Path $env:LOCALAPPDATA 'FujimiShinbunBunko\signing'
if ($Release) {
  New-Item -ItemType Directory -Path $signingDir -Force | Out-Null
  $signingKey = Join-Path $signingDir 'next-release.p12'
  $credentialsFile = Join-Path $signingDir 'next-release.credentials.xml'
  if ((Test-Path -LiteralPath $signingKey) -ne (Test-Path -LiteralPath $credentialsFile)) {
    throw 'Signing key or its protected credentials are missing; restore the matching pair before building.'
  }
  if (Test-Path -LiteralPath $credentialsFile) {
    $credentials = Import-Clixml -LiteralPath $credentialsFile
  } else {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $password = [Convert]::ToBase64String($bytes)
    $credentials = [pscredential]::new('fujimi-next', (ConvertTo-SecureString -String $password -AsPlainText -Force))
  }
  $env:FUJIMI_ANDROID_STORE_PASSWORD = $credentials.GetNetworkCredential().Password
  $env:FUJIMI_ANDROID_KEY_PASSWORD = $env:FUJIMI_ANDROID_STORE_PASSWORD
  $env:FUJIMI_ANDROID_KEYSTORE = $signingKey
  if (-not (Test-Path -LiteralPath $signingKey)) {
    $keytool = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin\keytool.exe' } else { 'keytool.exe' }
    & $keytool -genkeypair -keystore $signingKey -storetype PKCS12 -storepass:env FUJIMI_ANDROID_STORE_PASSWORD -keypass:env FUJIMI_ANDROID_KEY_PASSWORD -alias fujimi-next -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=Fujimi Shinbun Bunko Next, O=Fujimi, C=JP' -noprompt
    if ($LASTEXITCODE -ne 0) { throw 'Release signing key creation failed.' }
    $credentials | Export-Clixml -LiteralPath $credentialsFile
  }
}
Push-Location $android
try {
  if ($Clean) {
    & $Gradle clean --console=plain
    if ($LASTEXITCODE -ne 0) { throw "Android clean failed." }
  }
  if ($Release) {
    & $Gradle :core:test :app:assembleRelease --console=plain
  } else {
    & $Gradle :core:test :app:assembleDebug :app:assembleDebugAndroidTest --console=plain
  }
  if ($LASTEXITCODE -ne 0) { throw "Android debug build failed." }
} finally {
  Pop-Location
  if ($Release) {
    Remove-Item Env:FUJIMI_ANDROID_STORE_PASSWORD,Env:FUJIMI_ANDROID_KEY_PASSWORD,Env:FUJIMI_ANDROID_KEYSTORE -ErrorAction SilentlyContinue
    $password = $null
    $credentials = $null
  }
}

$variant = if ($Release) { 'release' } else { 'debug' }
$source = Join-Path $env:USERPROFILE ".gradle\fujimi-android-build\app\outputs\apk\$variant\app-$variant.apk"
$destinationDir = Join-Path $repo "dist\FujimiShinbunBunkoAndroid"
New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
$filename = "FujimiShinbunBunkoAndroid-$variant.apk"
$destination = Join-Path $destinationDir $filename
Copy-Item -LiteralPath $source -Destination $destination -Force
$hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $destinationDir "$filename.sha256") -Value "$hash  $filename" -Encoding ascii
Write-Output "APK: $destination"
Write-Output "SHA256: $hash"
