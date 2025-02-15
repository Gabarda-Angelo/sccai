<!-- header.php  -->
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>POS | BARCODE SYSTEMS</title>

  <!-- Google Font: Source Sans Pro -->
  <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Source+Sans+Pro:300,400,400i,700&display=fallback">
  <!-- Font Awesome Icons -->
  <link rel="stylesheet" href="../plugins/fontawesome-free/css/all.min.css">
  <!-- iCheck for checkboxes and radio inputs -->
  <link rel="stylesheet" href="../plugins/icheck-bootstrap/icheck-bootstrap.min.css">
  <!-- Select2 -->
  <link rel="stylesheet" href="../plugins/select2/css/select2.min.css">
  <link rel="stylesheet" href="../plugins/select2-bootstrap4-theme/select2-bootstrap4.min.css">
  <!-- DataTables -->
  <link rel="stylesheet" href="../plugins/datatables-bs4/css/dataTables.bootstrap4.min.css">
  <link rel="stylesheet" href="../plugins/datatables-responsive/css/responsive.bootstrap4.min.css">
  <link rel="stylesheet" href="../plugins/datatables-buttons/css/buttons.bootstrap4.min.css">
  <!-- SweetAlert2 -->
  <link rel="stylesheet" href="../plugins/sweetalert2/sweetalert2.min.css">
  <!-- Theme style -->
  <link rel="stylesheet" href="../dist/css/sccpos.css">
  
  <style>
    /* Optional: style disabled links to look different */
    .nav-link.disabled {
      opacity: 0.6;
      pointer-events: none;
    }
  </style>
  
</head>

<body class="hold-transition sidebar-mini">
  <div class="wrapper">

    <!-- Navbar -->
    <nav class="main-header navbar navbar-expand navbar-white navbar-light">
      <!-- Left navbar links -->
      <ul class="navbar-nav">
        <li class="nav-item">
          <a class="nav-link" data-widget="pushmenu" href="#" role="button">
            <i class="fas fa-bars"></i>
          </a>
        </li>
      </ul>
    </nav>
    <!-- /.navbar -->

    <!-- Main Sidebar Container -->
    <aside class="main-sidebar sidebar-dark-primary elevation-4">
      <!-- Brand Logo -->
      <a href="index3.html" class="brand-link">
        <img src="../dist/img/scclogoheader.png" class="brand-image-xl elevation-1" style="opacity: .8">
      </a>

      <!-- Sidebar -->
      <div class="sidebar">
        <!-- Sidebar user panel (optional) -->
        <div class="user-panel mt-3 pb-3 mb-3 d-flex">
          <div class="image">
            <img src="../dist/img/avatar5.png" class="img-circle elevation-1" alt="User Image">
          </div>
          <div class="info">
            <a href="#" class="d-block">
              <?php echo htmlspecialchars($_SESSION['first_name'] . ' (' . $_SESSION['role'] . ')', ENT_QUOTES, 'UTF-8'); ?>
            </a>
          </div>
        </div>

        <!-- Sidebar Menu -->
        <?php
          // Determine if the logged-in user is a Cashier
          $isCashier = (isset($_SESSION['role']) && $_SESSION['role'] === 'Cashier');
          // Tooltip text for disabled features
          $tooltip = "Only Admin can access this features sorry";
        ?>
        <nav class="mt-2">
          <ul class="nav nav-pills nav-sidebar flex-column" data-widget="treeview" role="menu" data-accordion="false">
            <!-- POS: Always enabled -->
            <li class="nav-item">
              <a href="pos.php" class="nav-link">
                <i class="nav-icon fas fa-desktop"></i>
                <p>POS</p>
              </a>
            </li>

            <!-- Inventory Menu -->
            <li class="nav-item">
              <?php if ($isCashier): ?>
                <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
              <?php else: ?>
                <a href="#" class="nav-link">
              <?php endif; ?>
                  <i class="nav-icon fas fa-archive"></i>
                  <p>
                    Inventory
                    <i class="fas fa-angle-left right"></i>
                  </p>
                </a>
              <ul class="nav nav-treeview">
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="category.php" class="nav-link">
                  <?php endif; ?>
                      <i class="nav-icon fas fa-table"></i>
                      <p>Category</p>
                    </a>
                </li>
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="addproduct.php" class="nav-link">
                  <?php endif; ?>
                      <i class="nav-icon fas fa-edit"></i>
                      <p>Add Product</p>
                    </a>
                </li>
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="productlist.php" class="nav-link">
                  <?php endif; ?>
                      <i class="nav-icon fas fa-list"></i>
                      <p>Product List</p>
                    </a>
                </li>
              </ul>
            </li>

            <!-- Sales Report Menu -->
            <li class="nav-item">
              <?php if ($isCashier): ?>
                <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
              <?php else: ?>
                <a href="#" class="nav-link">
              <?php endif; ?>
                  <i class="nav-icon fas fa-chart-pie"></i>
                  <p>
                    Sales Report
                    <i class="fas fa-angle-left right"></i>
                  </p>
                </a>
              <ul class="nav nav-treeview">
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="tablereport.php" class="nav-link">
                  <?php endif; ?>
                      <i class="far fa-circle nav-icon"></i>
                      <p>Table Report</p>
                    </a>
                </li>
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="graphreport.php" class="nav-link">
                  <?php endif; ?>
                      <i class="far fa-circle nav-icon"></i>
                      <p>Graph Report</p>
                    </a>
                </li>
                <li class="nav-item">
                  <?php if ($isCashier): ?>
                    <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
                  <?php else: ?>
                    <a href="orderlist.php" class="nav-link">
                  <?php endif; ?>
                      <i class="far fa-circle nav-icon"></i>
                      <p>Invoice History</p>
                    </a>
                </li>
              </ul>
            </li>

            <!-- Registration -->
            <li class="nav-item">
              <?php if ($isCashier): ?>
                <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
              <?php else: ?>
                <a href="registration.php" class="nav-link">
              <?php endif; ?>
                  <i class="nav-icon fas fa-user"></i>
                  <p>Registration</p>
                </a>
            </li>

            <!-- Change Password -->
            <li class="nav-item">
              <?php if ($isCashier): ?>
                <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
              <?php else: ?>
                <a href="changepassword.php" class="nav-link">
              <?php endif; ?>
                  <i class="nav-icon fas fa-user-lock"></i>
                  <p>ChangePassword</p>
                </a>
            </li>

            <!-- ASK AI -->
            <li class="nav-item">
              <?php if ($isCashier): ?>
                <a href="#" class="nav-link" title="<?php echo $tooltip; ?>" style="cursor: not-allowed;">
              <?php else: ?>
                <a href="askai.php" class="nav-link">
              <?php endif; ?>
                  <i class="nav-icon fas fa-comments"></i>
                  <p>ASK AI</p>
                </a>
            </li>

            <!-- Logout -->
        
            <li class="nav-item">
                <a href="logout.php" class="nav-link">
            
                  <i class="nav-icon fas fa-sign-out-alt"></i>
                  <p>Logout</p>
                </a>
            </li>

          </ul>
        </nav>
        <!-- /.sidebar-menu -->
      </div>
      <!-- /.sidebar -->
    </aside>
