@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "NODE_COUNT=12"
set "BASE_PORT=8000"
set "DATA_DIR=data"

echo Khoi dong %NODE_COUNT% Edge Node...
echo Du lieu duoc luu tai: %DATA_DIR%
echo.

for /L %%I in (1,1,%NODE_COUNT%) do (
    set /A NODE_PORT=!BASE_PORT!+%%I
    set "PEERS="

    for /L %%J in (1,1,%NODE_COUNT%) do (
        if not %%I==%%J (
            set /A PEER_PORT=!BASE_PORT!+%%J

            if defined PEERS (
                set "PEERS=!PEERS!,edge-%%J=http://127.0.0.1:!PEER_PORT!"
            ) else (
                set "PEERS=edge-%%J=http://127.0.0.1:!PEER_PORT!"
            )
        )
    )

    echo Khoi dong edge-%%I tai cong !NODE_PORT!...

    start "edge-%%I" cmd /k python -m edge_node ^
        --id edge-%%I ^
        --port !NODE_PORT! ^
        --peers "!PEERS!" ^
        --data-dir "%DATA_DIR%"
)

timeout /t 8 /nobreak >nul
start "" http://localhost:8001

endlocal