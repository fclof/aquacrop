import numpy as np


from ..entities.initParamVariables import InitCondClass
from ..entities.modelConstants import ModelConstants


def read_model_initial_conditions(ParamStruct, ClockStruct, InitWC):
    """
    Function to set up initial model conditions

    *Arguments:*\n

    `ParamStruct` : `ParamStructClass` :  Contains model paramaters

    `ClockStruct` : `ClockStructClass` :  model time paramaters

    `InitWC` : `InitWCClass`:  initial water content


    *Returns:*

    `ParamStruct` : `ParamStructClass` :  updated ParamStruct object

    `InitCond` : `InitCondClass` :  containing initial model conditions/counters


    """

    ###################
    # creat initial condition class
    ###################

    InitCond = InitCondClass(len(ParamStruct.Soil.profile))

    # class_args = {key:value for key, value in InitCond_class.__dict__.items() if not key.startswith('__') and not callable(key)}
    # InitCond = InitCondStruct(**class_args)

    if ClockStruct.season_counter == -1:
        InitCond.Zroot = 0.
        InitCond.CC0adj = 0.

    elif ClockStruct.season_counter == 0:
        InitCond.Zroot = ParamStruct.Seasonal_Crop_List[0].Zmin
        InitCond.CC0adj = ParamStruct.Seasonal_Crop_List[0].CC0

    ##################
    # save field management
    ##################

    # Initial surface storage between any soil bunds
    if ClockStruct.season_counter == -1:
        # First day of simulation is in fallow period
        if (ParamStruct.FallowFieldMngt.bunds) and (
            float(ParamStruct.FallowFieldMngt.z_bund) > 0.001
        ):
            # Get initial storage between surface bunds
            InitCond.SurfaceStorage = float(ParamStruct.FallowFieldMngt.bund_water)
            if InitCond.SurfaceStorage > float(ParamStruct.FallowFieldMngt.z_bund):
                InitCond.SurfaceStorage = float(ParamStruct.FallowFieldMngt.z_bund)
        else:
            # No surface bunds
            InitCond.SurfaceStorage = 0

    elif ClockStruct.season_counter == 0:
        # First day of simulation is in first growing season
        # Get relevant field management structure parameters
        FieldMngtTmp = ParamStruct.FieldMngt
        if (FieldMngtTmp.bunds) and (float(FieldMngtTmp.z_bund) > 0.001):
            # Get initial storage between surface bunds
            InitCond.SurfaceStorage = float(FieldMngtTmp.bund_water)
            if InitCond.SurfaceStorage > float(FieldMngtTmp.z_bund):
                InitCond.SurfaceStorage = float(FieldMngtTmp.z_bund)
        else:
            # No surface bunds
            InitCond.SurfaceStorage = 0

    ############
    # watertable
    ############

    profile = ParamStruct.Soil.profile

    # Check for presence of groundwater table
    if ParamStruct.water_table == 0:  # No water table present
        # Set initial groundwater level to dummy value
        InitCond.zGW = ModelConstants.NO_VALUE
        InitCond.WTinSoil = False
        # Set adjusted field capacity to default field capacity
        InitCond.th_fc_Adj = profile.th_fc.values
    elif ParamStruct.water_table == 1:  # Water table is present
        # Set initial groundwater level
        InitCond.zGW = float(ParamStruct.zGW[ClockStruct.time_step_counter])
        # Find compartment mid-points
        zMid = profile.zMid
        # Check if water table is within modelled soil profile
        if InitCond.zGW >= 0:
            idx = zMid[zMid >= InitCond.zGW].index
            if idx.shape[0] == 0:
                InitCond.WTinSoil = False
            else:
                InitCond.WTinSoil = True
        else:
            InitCond.WTinSoil = False

        # Adjust compartment field capacity
        compi = int(len(profile)) - 1
        thfcAdj = np.zeros(compi + 1)
        while compi >= 0:
            # get soil layer of compartment
            compdf = profile.loc[compi]
            if compdf.th_fc <= 0.1:
                Xmax = 1
            else:
                if compdf.th_fc >= 0.3:
                    Xmax = 2
                else:
                    pF = 2 + 0.3 * (compdf.th_fc - 0.1) / 0.2
                    Xmax = (np.exp(pF * np.log(10))) / 100

            if (InitCond.zGW < 0) or ((InitCond.zGW - zMid.iloc[compi]) >= Xmax):
                for ii in range(compi):
                    compdfii = profile.loc[ii]
                    thfcAdj[ii] = compdfii.th_fc

                compi = -1
            else:
                if compdf.th_fc >= compdf.th_s:
                    thfcAdj[compi] = compdf.th_fc
                else:
                    if zMid.iloc[compi] >= InitCond.zGW:
                        thfcAdj[compi] = compdf.th_s
                    else:
                        dV = compdf.th_s - compdf.th_fc
                        dFC = (dV / (Xmax ** 2)) * ((zMid.iloc[compi] - (InitCond.zGW - Xmax)) ** 2)
                        thfcAdj[compi] = compdf.th_fc + dFC

                compi = compi - 1

        # Store adjusted field capacity values
        InitCond.th_fc_Adj = np.round(thfcAdj, 3)

    profile["th_fc_Adj"] = np.round(InitCond.th_fc_Adj, 3)

    # create hydrology df to group by layer instead of compartment
    ParamStruct.Soil.Hydrology = profile.groupby("Layer").mean().drop(["dz", "dzsum"], axis=1)
    ParamStruct.Soil.Hydrology["dz"] = profile.groupby("Layer").sum().dz

    ###################
    # initial water contents
    ###################

    typestr = InitWC.wc_type
    methodstr = InitWC.Method

    depth_layer = InitWC.depth_layer
    datapoints = InitWC.value

    values = np.zeros(len(datapoints))

    hydf = ParamStruct.Soil.Hydrology

    # Assign data
    if typestr == "Num":
        # Values are defined as numbers (m3/m3) so no calculation required
        depth_layer = np.array(depth_layer, dtype=float)
        values = np.array(datapoints, dtype=float)

    elif typestr == "Pct":
        # Values are defined as percentage of TAW. Extract and assign value for
        # each soil layer based on calculated/input soil hydraulic properties
        depth_layer = np.array(depth_layer, dtype=float)
        datapoints = np.array(datapoints, dtype=float)

        for ii in range(len(values)):
            if methodstr == "Depth":
                depth = depth_layer[ii]
                value = datapoints[ii]

                # Find layer at specified depth
                if depth < profile.dzsum.iloc[-1]:
                    layer = profile.query(f"{depth}<dzsum").Layer.iloc[0]
                else:
                    layer = profile.Layer.iloc[-1]

                compdf = hydf.loc[layer]

                # Calculate moisture content at specified depth
                values[ii] = compdf.th_wp + ((value / 100) * (compdf.th_fc - compdf.th_wp))
            elif methodstr == "Layer":
                # Calculate moisture content at specified layer
                layer = depth_layer[ii]
                value = datapoints[ii]

                compdf = hydf.loc[layer]

                values[ii] = compdf.th_wp + ((value / 100) * (compdf.th_fc - compdf.th_wp))

    elif typestr == "Prop":
        # Values are specified as soil hydraulic properties (SAT, FC, or WP).
        # Extract and assign value for each soil layer

        for ii in range(len(values)):
            if methodstr == "Depth":
                # Find layer at specified depth
                depth = depth_layer[ii]
                value = datapoints[ii]

                # Find layer at specified depth
                if depth < profile.dzsum.iloc[-1]:
                    layer = profile.query(f"{depth}<dzsum").Layer.iloc[0]
                else:
                    layer = profile.Layer.iloc[-1]

                compdf = hydf.loc[layer]

                # Calculate moisture content at specified depth
                if value == "SAT":
                    values[ii] = compdf.th_s
                if value == "FC":
                    values[ii] = compdf.th_fc
                if value == "WP":
                    values[ii] = compdf.th_wp

            elif methodstr == "Layer":
                # Calculate moisture content at specified layer
                layer = depth_layer[ii]
                value = datapoints[ii]

                compdf = hydf.loc[layer]

                if value == "SAT":
                    values[ii] = compdf.th_s
                if value == "FC":
                    values[ii] = compdf.th_fc
                if value == "WP":
                    values[ii] = compdf.th_wp

    # Interpolate values to all soil compartments

    thini = np.zeros(int(profile.shape[0]))
    if methodstr == "Layer":
        for ii in range(len(values)):
            layer = depth_layer[ii]
            value = values[ii]

            idx = profile.query(f"Layer=={int(layer)}").index

            thini[idx] = value

        InitCond.th = thini

    elif methodstr == "Depth":
        depths = depth_layer

        # Add zero point
        if depths[0] > 0:
            depths = np.append([0], depths)
            values = np.append([values[0]], values)

        # Add end point (bottom of soil profile)
        if depths[-1] < ParamStruct.Soil.zSoil:
            depths = np.append(depths, [ParamStruct.Soil.zSoil])
            values = np.append(values, [values[-1]])

        # Find centroids of compartments
        SoilDepths = profile.dzsum.values
        comp_top = np.append([0], SoilDepths[:-1])
        comp_bot = SoilDepths
        comp_mid = (comp_top + comp_bot) / 2
        # Interpolate initial water contents to each compartment
        thini = np.interp(comp_mid, depths, values)
        InitCond.th = thini

    # If groundwater table is present and calculating water contents based on
    # field capacity, then reset value to account for possible changes in field
    # capacity caused by capillary rise effects
    if ParamStruct.water_table == 1:
        if (typestr == "Prop") and (datapoints[-1] == "FC"):
            InitCond.th = InitCond.th_fc_Adj

    # If groundwater table is present in soil profile then set all water
    # contents below the water table to saturation
    if InitCond.WTinSoil == True:
        # Find compartment mid-points
        SoilDepths = profile.dzsum.values
        comp_top = np.append([0], SoilDepths[:-1])
        comp_bot = SoilDepths
        comp_mid = (comp_top + comp_bot) / 2
        idx = np.where(comp_mid >= InitCond.zGW)[0][0]
        for ii in range(idx, len(profile)):
            layeri = profile.loc[ii].Layer
            InitCond.th[ii] = hydf.th_s.loc[layeri]

    InitCond.thini = InitCond.th

    ParamStruct.Soil.profile = profile
    ParamStruct.Soil.Hydrology = hydf

    return ParamStruct, InitCond

