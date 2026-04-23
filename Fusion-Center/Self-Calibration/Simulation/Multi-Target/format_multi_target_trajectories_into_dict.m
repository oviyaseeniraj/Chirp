dict = dictionary;

for i=1:num_targets
    for j=1:num_targets
        trajectory = [complex_trajectory_estimate_array(i, :); 
                      complex_trajectory_estimate_array(j+num_targets, :)];
        dict({[i, j]}) = mat2cell(trajectory, 2);
    end
end

save('trajectories_combinations_dict_test.mat', 'dict');